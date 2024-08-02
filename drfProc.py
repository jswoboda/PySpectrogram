#!/usr/bin/env python

# ============================================================================================================
#     Code: DrfProcessor.py
#     Author: Casey R. Densmore
#
#     Purpose: Handles all signal processing functions related to accessing microphones + converting PCM data to spectra
#
#   General Functions:
#       o freq,fftdata = dofft(pcmdata,fs,alpha): Runs fft on pcmdata with sampling frequency
#           fs using cosine taper (Tukey) defined by alpha
#   DrfProcessor Functions:
#       o __init__(datasource)
#       o Run(): A separate function called from main.py immediately after initializing the thread to start data
#           collection. Here, the callback function which updates the audio stream for WiNRADIO threads is declared
#           and the stream is directed to this callback function. This also contains the primary thread loop which
#           updates data from either the WiNRADIO or audio file continuously using dofft() and the conversion eqns.
#       o abort(): Aborts the thread, sends final data to the event loop and notifies the event loop that the
#           thread has been terminated
#       o terminate(errortype): terminates thread due to internal issue
#
#   ThreadProcessorSignals:
#       o iterated(ctabnum,ctemp, cdepth, cfreq, sigstrength, ctime, i): Passes information collected on the current
#           iteration of the thread loop back to the main program, in order to update the corresponding tab. "i" is
#           the iteration number- plots and tables are updated in the main loop every N iterations, with N specified
#           independently for plots/tables in main.py
#       o terminated(ctabnum): Notifies the main loop that the thread has been terminated/aborted
#       o terminated(flag): Notifies the main loop that an error (corresponding to the value of flag) occured, causing an
#           error message to be posted in the GUI
#       o updateprogress(ctabnum, progress): **For audio files only** updates the main loop with the progress
#           (displayed in progress bar) for the current thread
#
# ============================================================================================================

import numpy as np
from scipy.io import wavfile as sciwavfile  # for wav file reading
import scipy.signal as sig

import wave  # WAV file writing

from PyQt5.QtCore import pyqtSlot, pyqtSignal, QObject
from PyQt5.Qt import QRunnable

import time as timemodule

from traceback import print_exc as trace_error

from shutil import copy as shcopy
from os.path import exists
from sys import platform

import digital_rf as drf
from fractions import Fraction
from pathlib import Path


class DrfInput:

    def __init__(self, drfdir):
        drf_path = Path(drfdir).expanduser()
        self.drf_Obj = drf.DigitalRFReader(str(drf_path))
        chans = self.drf_Obj.get_channels()

        raw_chan_list = []
        self.chan_2sub = {}
        self.chan_entries = {}
        self.last_read = {}
        self.sr_dict = {}
        self.ref_dict = {}
        self.time_bnds = (np.inf, -np.inf)
        self.bnds = {}
        for ichan in chans:
            props = self.drf_Obj.get_properties(ichan)
            ref = get_ref(props)
            sr_f = Fraction(
                props["sample_rate_numerator"], props["sample_rate_denominator"]
            )
            bnds = self.drf_Obj.get_bounds(ichan)
            num_sub = props["num_subchannels"]
            self.chan_2sub[ichan] = {ichan: np.arange(num_sub)}
            self.bnds[ichan] = bnds
            self.time_bnds = (
                min(self.time_bnds[0], float(bnds[0] / sr_f)),
                max(self.time_bnds[1], float(bnds[1] / sr_f)),
            )
            self.sr_dict[ichan] = sr_f
            self.ref_dict[ichan] = ref
            self.last_read[ichan] = (None, None)
            for isub in range(num_sub):
                self.chan_entries[ichan + ":" + str(isub)] = (ichan, isub)

    def read(self, st_sample, n_sample, chan_entry, adj_bnds=False):
        """Reads the data from the drf file.

        Parameters
        ----------
        st_sample : int
            Start sample of the read in the number of samples since the ephoc.
        n_samples : int
            Number of time samples to be read.
        chan_entry : str
            Can either be the channel name or the channel name and subchannel number seperated with a `:`. If just the channel name then the output will be a ntimexnsub array, if it has the sub channel then there will be
        adj_bnds : bool
            If set true then will adjust the read position to the current bounds of the data set.

        Returns : ndarray
            The data read normalized to bitdepth.

        """
        if ":" in chan_entry:
            ichan, isub = self.chan_entries[chan_entry]
        else:
            ichan = chan_entry
            isub = None
        bnds = self.drf_Obj.get_bounds(ichan)
        ref = self.ref_dict[ichan]

        if adj_bnds:
            st_sample = max(st_sample, bnds[0])
            n_sample = min(bnds[1], n_sample + st_sample) - st_sample
        if isub is None:
            x = self.drf_Obj.read_vector(st_sample, n_sample, ichan)
        else:
            x = self.drf_Obj.read_vector(st_sample, n_sample, ichan, isub)
        self.bnds[ichan] = bnds
        self.last_read[ichan] = (st_sample, n_sample)
        x = x / ref
        return x
    
    def read_sti(self,st_sample, chan_entry, en_sample,nfft,nint,ntime):
        """Get the needed arrays for an STI from digital rf. The ending array will be an array of size (nfftxnint,ntime,nsub) where nfft is the number of nfft points, nint is the number of integrated ffts, ntime is the number of time elements and the nsub is the number of sub channels. This allows for the first axes to represent fft, integrate and then time.

        Parameters
        ----------
        st_sample : int
            Start sample of the read in the number of samples since the ephoc.
        chan_entry : str
            Can either be the channel name or the channel name and subchannel number seperated with a `:`. If just the channel name then the output will be a ntimexnsub array, if it has the sub channel then there will be
        en_sample : int
            End sample of the STI in the number of samples since the ephoc.
        nfft : int
            Number of points in the FFT.
        nint : int
            Number of integrations of the fft.
        ntime : int
            Number of time points of the fft
        
        Returns
        -------
        n_st : ndarray
            Array that holds first sample read for each time period
        dout : ndarray
            Array of samples read out is of shape of (nfftxnint,ntime,nsub).
        """
       
        n_sample = nint*nfft
        n_st = np.linspace(st_sample,en_sample-n_sample,ntime,dtype=int)
        dlist = []
        for ist in n_st: 
            d1 = self.read(ist,n_sample,chan_entry)
            d2 = d1[:,np.newaxis]
            dlist.append(d2)

        dout = np.concatenate(dlist,axis=1)
        return n_st, dout
    
    def bnds_update(self):
        """Update the internal bounds in the class."""
        chans = list(self.chan_2sub.keys())
        for ichan in chans:
            bnds = self.drf_Obj.get_bounds(ichan)
            sr_f = self.sr_dict[ichan]
            self.bnds[ichan] = bnds
            self.time_bnds = (
                min(self.time_bnds[0], float(bnds[0] / sr_f)),
                max(self.time_bnds[1], float(bnds[1] / sr_f)),
            )


def get_ref(prop_dict):
    """Determines the reference to get everything in dBFS. If int divides by the size 2**(nbits) adds 1 half bit for complex data.

    Parameters
    ----------
    prop_dict : dict
        Dictionary from get_properties command on the drf channel.

    Returns
    -------
    :float
        ref level of data.
    """
    # HACK if data is a float assuming that FS is power of 1.

    if prop_dict["H5Tget_class"] == 1:
        return 1.0
    npow = prop_dict["H5Tget_precision"] - 1.0
    npow += 0.5 * (prop_dict["H5Tget_size"] - 1.0)
    return 2**npow


# =============================================================================
#  READ SIGNAL FROM WINRADIO, OUTPUT TO PLOT, TABLE, AND DATA
# =============================================================================


class DrfProcessor(QRunnable):

    # initializing current thread (saving variables, reading audio data or contacting/configuring receiver)
    def __init__(
        self, datasource, drfdir, tabID, fftbins, n_int, ntime, *args, **kwargs
    ):
        #fftwindow is number of seconds for fft.
        # in the original software dt was the sample time, fs was the sampling frequency. 
        # dt is time between ffts in the original code. basically controls the overlap.

        super(DrfProcessor, self).__init__()

        self.drfIn = DrfInput(drfdir)

        self.drf_path = Path(drfdir).expanduser()
        # UI inputs
        self.tabID = tabID
        self.fftbins = fftbins
        self.n_int = n_int
        self.ntime = ntime
        self.bnds = self.drfIn.time_bnds
        self.chan_listing = list(self.drfIn.chan_entries.keys())
        # initializing inner workings
        self.isrunning = False  # set to true while running
        self.signals = ThreadProcessorSignals()  # signal connections

        self.reason = 0

        # output audio (WAV) file name- saving in temporary folder passed from event loop
        if datasource.lower() == "streaming":
            self.streaming = True
            self.streamtime = 30
        else:
            self.streaming = False
            self.streamtime = None
        if not self.drf_path.exists():
            self.terminate(1)

        self.isrunning = True
    
    @pyqtSlot()
    def run(self):

        # barrier to prevent signal processor loop from starting before __init__ finishes
        counts = 0
        while not self.isrunning:
            counts += 1
            if self.reason:
                return
            elif counts > 100:
                self.terminate(3)
                return

            timemodule.sleep(0.1)

        if (self.reason):  
            # just in case timing issues allow the while loop to terminate and then the reason is changed
            return
        # if the Run() method gets this far, __init__ has completed successfully (and set self.startthread = 100)
   
        try:
            # setting up thread while loop- terminates when user clicks "STOP" or audio file finishes processing
            i = -1

            while self.isrunning:
                i += 1
                # storing FFT settings (this can't happen in __init__ because it might emit updated settings before the slot is connected)
                
                # update teh bounds
                self.drfIn.bnds_update()
                self.updatesettings(self.fftbins, self.n_int,self.ntime, self.drfIn.time_bnds[0], self.drfIn.time_bnds[1])
                if self.streaming:
                    end_time = self.drfIn.time_bnds[-1]
                    st_time = end_time-self.streamtime

                else:
                    st_time, end_time = self.bnds

                for ichan in self.drfIn.chan_2sub.keys():
                    sr = self.drfIn.sr_dict[ichan]
                    s_samp = drf.util.time_to_sample(st_time,sr)
                    e_samp = drf.util.time_to_sample(end_time,sr)
                    n_st, d1 = self.drfIn.read_sti(s_samp,ichan,e_samp,self.fftbins,self.n_int,self.ntime)
                    time_list = [drf.util.sample_to_datetime(istime, int(sr)) for istime in n_st]
                    time_ar = np.concatinate(time_list)
                    f, sxx, sxx_med = sti_proc_data(d1,sr,self.fftbins)
                    self.freqs_all = f
                    self.signals.iterated.emit(
                            i,self.tabID, time_ar, self.freqs_all, sxx, sxx_med
                        )
 
                if self.streaming:
                    timemodule.sleep(0.08)  # tiny pause to free resources

                else:  # wait for time threshold before getting next point

                    timemodule.sleep(0.1)

        except Exception:  # if the thread encounters an error, terminate
            self.isrunning = False
            self.terminate(4)

            trace_error()  # if there is an error, terminates processing



    @pyqtSlot(float, float, float,float,float)
    def updatesettings_slot(self, fftbins,nint,ntime,bnd_beg,bnd_end):  # update data thresholds for FFT
        self.updatesettings( fftbins,nint,ntime,bnd_beg,bnd_end)

    def updatesettings(self, fftbins,nint,ntime,bnd_beg,bnd_end):  # update data thresholds for FFT
        self.fftbins = int(fftbins)
        self.n_int = int(nint)
        self.ntime = int(ntime)
        self.bnds = (bnd_beg,bnd_end)
        self.signals.statsupdated.emit(self.tabID,self.fftbins,self.n_int,self.ntime,self.bnds)

    @pyqtSlot()
    def abort(self):  # executed when user selects "Stop" button
        self.terminate(
            0
        )  # terminates with exit code 0 (no error because user initiated quit)
        return

    def terminate(self, reason):
        self.reason = reason
        self.isrunning = False  # guarantees that event loop ends


        # signal that tab indicated by curtabnum was closed due to reason indicated by variable 'reason'
        self.signals.terminated.emit(
            self.tabID, reason
        )  # notify event loop that processor has stopped


def sti_proc_data(d1, sr, nfft):
    """Creates an STI, assumes that the data dimentions are the following (nfft*nint,ntime,nsub). The output array of sxx will be (nfft,ntime,nsub).

    Parameters
    ----------
    d1 : array_like
        Input data in shape of (nfft*nint,ntime,nsub).
    sr : float
        Sampling rate in Hz
    nfft : int
        Number of FFT bins in spectra.


    Returns
    -------
    f : array_like
        Frequency array of spectrum in Hz.
    sxx : array_like
        STI data in (nfft,ntime,nsub) array.
    sxx_med : array_like
        Median across time of the STI
    """
    win = sig.get_window(("kaiser", 1.7), nfft)
    f, pxx = sig.periodogram(
        d1, sr, window=win, nfft=nfft,detrend=False, return_onesided=False, scaling="spectrum", axis=0)
  

    f = np.fft.fftshift(f)
    sxx = np.fft.fftshift(pxx, axes=0)

    sxx_med = np.median(sxx,axis=1)

    return f, sxx, sxx_med

def proc_data(d1, sr, nfft, dt):
    """Creates a STI, min median and max spectra.

    Parameters
    ----------
    d1 : array_like
        Input data.
    sr : float
        Sampling rate in Hz
    nfft : int
        Number of FFT bins in spectra.
    dt : float
        For each time instance of the STI will integrate over this period.

    Returns
    -------
    t_out : array_like
        Time array output in seconds from STI.
    f : array_like
        Frequency array of spectrum in Hz.
    sxx_int : array_like
        STI data
    sxx_med : array_like
        Median across time of the STI
    sxx_min : array_like
        Minimum across the time of the STI
    sxx_max : array_like
        Maximum across the time of the STI.
    """
    win = sig.get_window(("kaiser", 1.7), nfft)
    f, t, sxx = sig.spectrogram(
        d1, sr, window=win, detrend=False, return_onesided=False, scaling="spectrum"
    )
    n_int = int(dt / (t[1] - t[0]))
    n1 = np.arange(0, len(t), n_int)

    sxx_int = np.zeros((nfft, len(n1) - 1), dtype=sxx.dtype)
    for i in range(len(n1[:-1])):
        sxx_chunk = sxx[:, n1[i] : n1[i + 1]]
        sxx_int[:, i] = np.mean(sxx_chunk, axis=-1)

    t_out = t[n1][:-1]
    f = np.fft.fftshift(f)
    sxx_int = np.fft.fftshift(sxx_int, axes=0)

    sxx_med = np.median(sxx_int, axis=-1)

    return t_out, f, sxx_int, sxx_med


# TODO: CONFIGURE THESE
# initializing signals for data to be passed back to main loop
class ThreadProcessorSignals(QObject):
    iterated = pyqtSignal(
        int, int, int, np.ndarray, np.ndarray,np.ndarray
    )  # signal to add another entry to raw data arrays
    statsupdated = pyqtSignal(int, int, float, int, tuple)
    terminated = pyqtSignal(
        int, int
    )  # signal that the loop has been terminated (by user input or program error)

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
from scipy.io import wavfile as sciwavfile #for wav file reading
import scipy.signal as sig

import wave #WAV file writing

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


class DrfInput():

    def __init__(self,drfdir):
        drf_path = Path(drfdir).expanduser()
        self.drf_Obj = drf.DigitalRFReader(str(drf_path))
        chans = self.drf_Obj.get_channels()

        raw_chan_list = []
        self.chan_2sub = {}
        self.chan_entries = {}
        self.last_read = {}
        self.sr_dict = {}
        self.ref_dict = {}
        self.time_bnds = (np.inf,-np.inf)
        for ichan in chans:
            props = self.drf_Obj.get_properties(ichan)
            ref = get_ref(props)
            sr_f = Fraction(props["sample_rate_numerator"],props["sample_rate_denominator"])
            bnds = self.drf_Obj.get_bounds(ichan)
            num_sub = props['num_subchannls']
            self.chan_2sub[ichan] = {ichan:np.arange(num_sub)}
            self.bnds[ichan] = bnds
            self.time_bnds = (min(self.time_bnds[0],float(bnds[0]/sr_f)), max(self.time_bnds[1],float(bnds[1]/sr_f)))
            self.sr_dict[ichan] = sr_f
            self.ref_dict[ichan] = ref
            self.last_read[ichan] = (None,None)
            for isub in range(num_sub):
                self.chan_entries[ichan+":"+str(isub)] = (ichan,isub)
                
    def read(self,st_sample,n_sample,chan_entry,adj_bnds = False):
        """Reads the data from the drf file.


    
        """
        if ":" in chan_entry:
            ichan,isub = self.chan_entries[chan_entry]
        else:
            ichan = chan_entry
            isub = None    
        bnds = self.drf_Obj.get_bounds(ichan)
        ref = self.ref_dict[ichan]
        
        if adj_bnds:
            st_sample = max(st_sample,bnds[0])
            n_sample = min(bnds[1],n_sample+st_sample)-st_sample
        if isub is None:
            x = self.drf_Obj.read_vector(st_sample,n_sample,ichan)
        else:
            x = self.drf_Obj.read_vector(st_sample,n_sample,ichan,isub)
        self.bnds[ichan] = bnds
        self.last_read[ichan] = (st_sample,n_sample)
        x = x/ref
        return x
    
    def bnds_update(self):
        """
        
        """
        chans = list(self.chan2_sub.keys())
        for ichan in chans:
            bnds = self.drf_Obj.get_bounds(ichan)
            sr_f = self.sr_dict[ichan]
            self.bnds[ichan] = bnds
            self.time_bnds = (min(self.time_bnds[0],float(bnds[0]/sr_f)), max(self.time_bnds[1],float(bnds[1]/sr_f)))

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

    #initializing current thread (saving variables, reading audio data or contacting/configuring receiver)
    def __init__(self, datasource,drfdir, tabID, fftbins, n_int,lensig,dt, *args,**kwargs):

        super(DrfProcessor, self).__init__()

        self.drfIn = DrfInput(drfdir)
        chan = [self.drfIn.sr_dict.keys()][0]
        sr = self.drfIn.sr_dict[chan]
        self.drf_path = Path(drfdir).expanduser()
        # UI inputs
        self.tabID = tabID
        self.fftbins = fftbins
        self.n_int = n_int
        self.lensig = lensig
        self.dt = dt
        self.samp_read = np.arange(int(lensig/dt))*int(sr)

        #initializing inner workings
        self.isrunning = False  #set to true while running
        self.signals = ThreadProcessorSignals() # signal connections
        
        self.reason = 0
        
        #output audio (WAV) file name- saving in temporary folder passed from event loop
        if datasource[:3] == 'streaming':
            self.streaming=True
        else:
            self.streaming = False
        if not self.drf_path.exists():
            self.terminate(1)
                        
                
           
        self.isrunning = True
        
        

    @pyqtSlot()
    def run(self):
        
        #barrier to prevent signal processor loop from starting before __init__ finishes
        counts = 0
        while not self.isrunning:
            counts += 1
            if self.reason:
                return
            elif counts > 100:
                self.terminate(3)
                return
                
            timemodule.sleep(0.1)
            
        if self.reason: #just in case timing issues allow the while loop to terminate and then the reason is changed
            return
        #if the Run() method gets this far, __init__ has completed successfully (and set self.startthread = 100)
        
        
        #storing FFT settings (this can't happen in __init__ because it might emit updated settings before the slot is connected)
        self.changethresholds(self.fftwindow,self.dt)
        
        if self.fromAudio: #if source is an audio file 
            self.sampletimes = np.arange(0,self.lensignal/self.fs,self.dt) #sets times to sample from file
            self.maxnum = len(self.sampletimes)
            
        else: #using live mic for data source
            self.maxnum = 0 #TODO: ADD INITIALIZATION STUFF HERE
            try:

                def updatedrfbuffer(bufferdata):
                    try:
                        if self.isrunning:
                            pass
                    except Exception:
                        trace_error()  
                        self.terminate(5)
                        returntype = None
                    finally:
                        return (None, returntype)
                #CALLBACK FUNCTION HERE
                def updateaudiobuffer(bufferdata, nframes, time_info, status):
                    try:
                        if self.isrunning:
                            self.audiostream.extend(bufferdata[:]) #append data to end
                            del self.audiostream[:nframes] #remove data from start
                            wave.Wave_write.writeframes(self.wavfile, bytearray(bufferdata))
                            returntype = pyaudio.paContinue
                        else:
                            returntype = pyaudio.paAbort
                    except Exception:
                        trace_error()  
                        self.terminate(5)
                        returntype = pyaudio.paAbort
                    finally:
                        return (None, returntype)
                    #end of callback function
                    
                #initializing and starting (start=True) pyaudio device input stream to callback function
                if platform.lower() == "darwin": #MacOS specific stream info input
                    self.stream = pyaudio.Stream(self.p, self.fs, 1, self.frametype, input=True, output=False, input_device_index=self.audiosourceindex, start=True, stream_callback=updateaudiobuffer, input_host_api_specific_stream_info=pyaudio.PaMacCoreStreamInfo())
                else: #windows or linux
                    self.stream = pyaudio.Stream(self.p, self.fs, 1, self.frametype, input=True, output=False, input_device_index=self.audiosourceindex, start=True, stream_callback=updateaudiobuffer)
                    
            except Exception:
                trace_error()
                self.terminate(2)
        
                
                
        try:
            # setting up thread while loop- terminates when user clicks "STOP" or audio file finishes processing
            i = -1

            while self.isrunning:
                i += 1
                if self.streaming:
                    self.drfIn.bnds_update()
                    next_read = {}
                    for ient, (ist,inum) in self.drfIn.last_read.items():
                        ichan in self.drfIn.chan_entries[ient][0]
                        cur_bnds = self.drfIn.bnds[ichan]
                        old_max = inum+ist
                        new_st = min(old_max,cur_bnds[-1]-nread)
                        new_inum = min(cur_bnds[-1]-new_st,nread)
                        next_read[ient] = (new_st,new_inum)
                else:
                    next_read = {}
                    t_st, nread = get_next_read()
                    for ient, (ist,inum) in self.drfIn.last_read.items():
                        ichan in self.drfIn.chan_entries[ient][0]
                        sr_f = self.drfIn.sr_dict[ichan]
                        cur_bnds = self.drfIn.bnds[ichan]
                        old_max = inum+ist
                        new_st = max(cur_bnds[0],int(sr_f*t_st))
                        new_inum = min(cur_bnds[-1]-new_st,nread)
                        next_read[ient] = (new_st,new_inum)

                for ichan,isubs in self.drfIn.chan_2sub.items():

                    ient = ichan+":"+str(isub)
                    ref = self.ref_dict(ichan)
                    new_st,newnread = next_read[ient]
                    d1 = self.drfIn.read(new_st, newnread, ichan)
                    sr = self.drfIn.sr_dict[ichan]
                    for isub in isubs:
                        t_out, f, sxx_int, sxx_med = proc_data(d1[...,isub], self.sr, self.nfft, dt)

                        self.signals.iterated(i,self.maxnum,self.tabID,t_out,f,sxx_int,sxx_med)
                # finds time from processor start in seconds
                curtime = dt.datetime.utcnow()  # current time
                deltat = curtime - self.starttime

                #pulling PCM data segment
                if self.fromAudio:
                    
                    if i < self.maxnum:
                        ctime = self.sampletimes[i] #center time for current sample
                    else:
                        self.terminate(0)
                        return
                        
                    ctrind = int(np.round(ctime*self.fs))
                    pmind = int(self.fftbins/2)
                    
                    if ctrind - pmind >= 0 and ctrind + pmind < self.lensignal:       
                        pcmdata = self.audiostream[ctrind-pmind:ctrind+pmind]
                    else:
                        pcmdata = None
                        

                else:
                    ctime = deltat.total_seconds()
                    pcmdata = np.array(self.audiostream[-self.fftbins:])
                
                if pcmdata is not None:
  
                    spectra = self.dofft(pcmdata)
                    self.signals.iterated.emit(i,self.maxnum,self.tabID,ctime,spectra) #sends current PSD/frequency, along with progress, back to event loop
                        
                if self.fromAudio:
                    timemodule.sleep(0.08)  # tiny pause to free resources
                    
                else: #wait for time threshold before getting next point
                    
                        timemodule.sleep(0.1)  
                    

        except Exception: #if the thread encounters an error, terminate
            self.isrunning = False
            self.terminate(4)
            
            trace_error()  # if there is an error, terminates processing
            
    
            
    





    # #function to run fft here
    # def dofft(self, pcmdata): 
        
    #     if self.alpha > 0: #applying Tukey taper if necessary
    #         if pcmdata.shape[0] == self.taperlen: 
    #             ctaper = self.taper
    #         else:
    #             self.taper = tukey(pcmdata.shape[0], alpha=self.alpha)
    #         pcmdata = pcmdata*self.taper
        
    #     # conducting fft, calculating PSD
    #     spectra = np.abs(np.fft.fft(pcmdata)**2)/self.df #PSD = |X(f)^2| / df
    #     spectra[np.isinf(spectra)] = 1.0E-8 #replacing negative inf values (spectra power=0) with -1
    
    #     #limiting data to positive/real frequencies only (and convert to dB)

    #     spectra = np.log10(spectra[self.keepind])
        
    #     return spectra
            
    
        
        
    def calc_settings(self):
        
        if self.fftbins%2: #N must be even
            self.fftbins += 1

        
        self.df = self.fs/self.fftbins
        self.freqs_all = np.array([self.df * n if n < self.fftbins / 2 else self.df * (n - self.fftbins) for n in range(self.fftbins)])
        self.keepind = np.greater_equal(self.freqs_all,0)
        self.freqs = self.freqs_all[self.keepind]
                
        self.signals.statsupdated.emit(self.tabID,self.fs,self.df,self.fftbins,self.freqs)
        
        
        
        
        
    @pyqtSlot(float,float,float)
    def changethresholds_slot(self,fftwindow): #update data thresholds for FFT
        self.changethresholds(fftwindow)
        
        
    
    def changethresholds(self,fftwindow): #update data thresholds for FFT
        if fftwindow <= 1:
            self.fftwindow = fftwindow
        else:
            self.fftwindow = 1

        self.calc_settings()
        
        
        
        
    @pyqtSlot()
    def abort(self): #executed when user selects "Stop" button
        self.terminate(0) #terminates with exit code 0 (no error because user initiated quit)
        return
        
        
    def terminate(self,reason):
        self.reason = reason
        self.isrunning = False #guarantees that event loop ends
        
        #close audio file, terminate mic buffer
        if not self.fromAudio:
            wave.Wave_write.close(self.wavfile)
            self.stream.stop_stream()
            self.stream.close()
        
        #signal that tab indicated by curtabnum was closed due to reason indicated by variable 'reason'
        self.signals.terminated.emit(self.tabID,reason) #notify event loop that processor has stopped
        
        
        
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
     
        
#TODO: CONFIGURE THESE
#initializing signals for data to be passed back to main loop
class ThreadProcessorSignals(QObject): 
    iterated = pyqtSignal(int,int,int,float,np.ndarray) #signal to add another entry to raw data arrays
    statsupdated = pyqtSignal(int,int,float,int,np.ndarray)
    terminated = pyqtSignal(int,int) #signal that the loop has been terminated (by user input or program error)
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    

#!/usr/bin/env python3
# =============================================================================
#     Code: mainprogram.py
#     Author: Casey R. Densmore, 25JUN2019
#
#     Purpose: Creates QMainWindow class with basic functions for a GUI with
#        	multiple tabs. Requires PyQt5 module (pip instal PyQt5)
#
#   General functions within main.py "RunProgram" class of QMainWindow:
#       o __init__: Calls functions to initialize GUI
#       o initUI: Builds GUI window
# 		o makenewtab: Creates a new tab window (make all widgets/buttons here)
#       o whatTab: gets identifier for open tab
#       o renametab: renames open tab
#       o setnewtabcolor: sets the background color pattern for new tabs
#       o closecurrenttab: closes open tab
#       o savedataincurtab: saves data in open tab (saved file types depend on tab type and user preferences)
#       o postwarning: posts a warning box specified message
#       o posterror: posts an error box with a specified message
#       o postwarning_option: posts a warning box with Okay/Cancel options
#       o closeEvent: pre-existing function that closes the GUI- function modified to prompt user with an "are you sure" box
#
# =============================================================================


# =============================================================================
#   CALL NECESSARY MODULES HERE
# =============================================================================
from sys import argv, exit
import time
from platform import system as cursys
from struct import calcsize
from pathlib import Path
import shutil
from traceback import print_exc as trace_error
from datetime import datetime

if cursys() == "Windows":
    from ctypes import windll

from shutil import copy as shcopy

from PyQt5.QtWidgets import (
    QMainWindow,
    QAction,
    QApplication,
    QMenu,
    QLineEdit,
    QLabel,
    QSpinBox,
    QCheckBox,
    QPushButton,
    QMessageBox,
    QWidget,
    QFileDialog,
    QComboBox,
    QTextEdit,
    QTabWidget,
    QVBoxLayout,
    QInputDialog,
    QGridLayout,
    QDoubleSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QProgressBar,
    QDesktopWidget,
    QStyle,
    QStyleOptionTitleBar,
    QSlider,
    QRadioButton,
)
from PyQt5.QtCore import QObjectCleanupHandler, Qt, pyqtSlot, pyqtSignal, QObject
from PyQt5.QtGui import QIcon, QColor, QPalette, QBrush, QLinearGradient, QFont
from PyQt5.Qt import QThreadPool

from scipy.io import wavfile as sciwavfile
import wave

import numpy as np
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.colors import ListedColormap, Normalize
from matplotlib import cm
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
matplotlib.use('Qt5Agg')
import drfProc as dp

import digital_rf as drf
from fractions import Fraction
import ipdb


#   DEFINE CLASS FOR PROGRAM (TO BE CALLED IN MAIN)
class RunProgram(QMainWindow):

    # =============================================================================
    #   INITIALIZE WINDOW, INTERFACE
    # =============================================================================
    def __init__(self):
        super().__init__()

        try:
            self.initUI()  # creates GUI window
            self.buildmenu()  # Creates interactive menu, options to create tabs and start autoQC
            self.makenewtab()  # Opens first tab

        except Exception:
            trace_error()
            self.posterror("Failed to initialize the program.")

    def initUI(self):

        # setting window size
        cursize = QDesktopWidget().availableGeometry(self).size()
        titleBarHeight = self.style().pixelMetric(
            QStyle.PM_TitleBarHeight, QStyleOptionTitleBar(), self
        )
        self.resize(cursize.width(), cursize.height() - titleBarHeight)

        # setting title/icon, background color
        self.setWindowTitle("DRFRealtimeSpectrogram")
        # self.setWindowIcon(QIcon('pathway_to_icon_here.png')) #TODO: Create/include icon
        p = self.palette()
        p.setColor(self.backgroundRole(), QColor(255, 255, 255))  # white background
        self.setPalette(p)

        # sets app ID to ensure that any additional windows appear under the same tab
        if cursys() == "Windows":
            myappid = "PyRealtimeSpectrogram"  # arbitrary string
            windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

        # changing font size
        font = QFont()
        font.setPointSize(11)
        font.setFamily("Arial")
        self.setFont(font)

        # prepping to include tabs
        mainWidget = QWidget()
        self.setCentralWidget(mainWidget)
        mainLayout = QVBoxLayout()
        mainWidget.setLayout(mainLayout)
        self.tabWidget = QTabWidget()
        mainLayout.addWidget(self.tabWidget)
        self.myBoxLayout = QVBoxLayout()
        self.tabWidget.setLayout(self.myBoxLayout)
        self.show()

        # setting up dictionary to store data for each tab
        self.alltabdata = []

        # tab tracking
        self.totaltabs = 0
        self.tabnumbers = []

        # default directory

        defaultpath = Path("~").expanduser()
        if defaultpath.joinpath(
            "Documents"
        ).exists():  # default to Documents directory if it exists, otherwise home directory
            defaultpath = defaultpath.joinpath("Documents")
        self.defaultfiledir = defaultpath

        # setting up file dialog options
        self.fileoptions = QFileDialog.Options()
        self.fileoptions |= QFileDialog.DontUseNativeDialog

        # HACK set to written for now
        # identifying use method["streaming", "written"]
        self.usetype = "written"

        self.audioWindowOpened = False

        # creating threadpool
        self.threadpool = QThreadPool()
        self.threadpool.setMaxThreadCount(7)

        self.maxNfreqs = int(2**15)  # max number of frequency datapoints to plot

    # =============================================================================
    #    BUILD MENU, GENERAL SETTINGS
    # =============================================================================

    # builds file menu for GUI
    def buildmenu(self):
        # setting up primary menu bar
        menubar = self.menuBar()
        FileMenu = menubar.addMenu("Options")

        # File>New Tab
        newptab = QAction("&New Tab", self)
        newptab.setShortcut("Ctrl+N")
        newptab.triggered.connect(self.makenewtab)
        FileMenu.addAction(newptab)

        # File>Rename Current Tab
        renametab = QAction("&Rename Current Tab", self)
        renametab.setShortcut("Ctrl+R")
        renametab.triggered.connect(self.renametab)
        FileMenu.addAction(renametab)

        # File>Close Current Tab
        closetab = QAction("&Close Current Tab", self)
        closetab.setShortcut("Ctrl+X")
        closetab.triggered.connect(self.closecurrenttab)
        FileMenu.addAction(closetab)

    # =============================================================================
    #     SIGNAL PROCESSOR TAB AND INPUTS HERE
    # =============================================================================
    def makenewtab(self):
        try:

            curtabnum = self.addnewtab()

            # creates dictionary entry for current tab- you can add additional key/value combinations for the opened tab at any point after the dictionary has been initialized
            initstats = {
                "updated": False,
                "fs": None,
                "freqs": [],
                "N": None,
                "timerangemin": 0,
                "timerangemax": 10000,
                "fftlen": 128,
                "crange": [-70, -40],
                "nint": 0.1,
                "ntime": 100,
                "frange": [-1000, 1000],
            }

            self.alltabdata.append(
                {
                    "tab": QWidget(),
                    "tablayout": QGridLayout(),
                    "mainLayout": QGridLayout(),
                    "tabtype": "newtab",
                    "tabwidget": QTabWidget(),
                    "mainsettingswidget": QWidget(),
                    "plotsavewidget": QWidget(),
                    "signalmaskwidget": QWidget(),
                    "stats": initstats,
                    "isprocessing": False,
                    "Processor": None,
                    "chanselect": None,
                    "data": {
                        "maxtime": 0,
                        "times": np.array([]),
                        "freqs": np.array([]),
                        "spectra": np.array([[]]),
                        "timebnds": [],
                    },
                }
            )

            self.setnewtabcolor(self.alltabdata[curtabnum]["tab"])

            self.alltabdata[curtabnum]["tablayout"].setSpacing(10)

            # creating new tab, assigning basic info
            self.tabWidget.addTab(self.alltabdata[curtabnum]["tab"], "New Tab")
            self.tabWidget.setCurrentIndex(curtabnum)
            self.tabWidget.setTabText(curtabnum, "New Tab #" + str(self.totaltabs))
            _, self.alltabdata[curtabnum]["tabnum"] = (
                self.whatTab()
            )  # assigning unique, unchanging number to current tab
            self.alltabdata[curtabnum]["tablayout"].setSpacing(10)
            self.alltabdata[curtabnum]["mainLayout"].setSpacing(10)

            # and add new buttons and other widgets
            self.alltabdata[curtabnum]["tabwidgets"] = {}

            # creating plot
            self.alltabdata[curtabnum]["SpectroFig"] = plt.figure()
            self.alltabdata[curtabnum]["SpectroCanvas"] = FigureCanvas(
                self.alltabdata[curtabnum]["SpectroFig"]
            )
            self.alltabdata[curtabnum]["SpectroAxes"] = self.alltabdata[curtabnum]["SpectroCanvas"].figure.add_subplot(111)#plt.axes()
            self.alltabdata[curtabnum]["SpectroAxes"].set_ylabel("Time UTC")
            time_min = self.alltabdata[curtabnum]["stats"]["timerangemin"]
            time_max = self.alltabdata[curtabnum]["stats"]["timerangemax"]
            t_min, t_max = self.get_datetime_bnds(time_min,time_max)
            self.alltabdata[curtabnum]["SpectroAxes"].set_ylim(t_min, t_max)
            self.alltabdata[curtabnum]["SpectroAxes"].set_xlabel("Frequency (kHz)")
            self.alltabdata[curtabnum]["SpectroCanvas"].setStyleSheet(
                "background-color:transparent;"
            )
            self.alltabdata[curtabnum]["SpectroFig"].patch.set_facecolor("None")
            self.alltabdata[curtabnum]["SpectroFig"].set_tight_layout(True)
            self.alltabdata[curtabnum]["colorbar"] = self.gencolorbar(
                curtabnum, initstats["crange"]
            )

            self.alltabdata[curtabnum]["SpectroToolbar"] = CustomToolbar(
                self.alltabdata[curtabnum]["SpectroCanvas"], self
            )

            # creating tab widget
            self.alltabdata[curtabnum]["tabwidget"].setLayout(
                self.alltabdata[curtabnum]["tablayout"]
            )
            self.alltabdata[curtabnum]["tabwidget"].addTab(
                self.alltabdata[curtabnum]["mainsettingswidget"], "Spectrogram Settings"
            )
            self.alltabdata[curtabnum]["tabwidget"].addTab(
                self.alltabdata[curtabnum]["plotsavewidget"], "Save Spectrogram/Audio"
            )
            self.alltabdata[curtabnum]["mainsettingslayout"] = QGridLayout()
            self.alltabdata[curtabnum]["plotsavelayout"] = QGridLayout()
            self.alltabdata[curtabnum]["mainsettingswidget"].setLayout(
                self.alltabdata[curtabnum]["mainsettingslayout"]
            )
            self.alltabdata[curtabnum]["plotsavewidget"].setLayout(
                self.alltabdata[curtabnum]["plotsavelayout"]
            )
            self.alltabdata[curtabnum]["tabwidget"].setTabEnabled(1, False)

            # adding widgets to main layout
            self.alltabdata[curtabnum]["timelabel"] = QLabel("Center Time: 0/0 seconds")
            self.alltabdata[curtabnum]["timelabel"].setAlignment(
                Qt.AlignCenter | Qt.AlignVCenter
            )

            self.alltabdata[curtabnum]["mainLayout"].addWidget(
                self.alltabdata[curtabnum]["SpectroToolbar"], 1, 3, 1, 1
            )
            self.alltabdata[curtabnum]["mainLayout"].addWidget(
                self.alltabdata[curtabnum]["SpectroCanvas"], 2, 1, 1, 6
            )  # set dimensions
            self.alltabdata[curtabnum]["mainLayout"].addWidget(
                self.alltabdata[curtabnum]["tabwidget"], 3, 2, 1, 3
            )

            rowstretches = [1, 1, 30, 9, 1]
            for r, s in enumerate(rowstretches):
                self.alltabdata[curtabnum]["mainLayout"].setRowStretch(
                    r, s
                )  # stretching out row with plot axes

            colstretches = [1, 2, 2, 2, 2, 2, 1]
            for c, s in enumerate(colstretches):
                self.alltabdata[curtabnum]["mainLayout"].setColumnStretch(
                    c, s
                )  # stretching out row with plot axes

            # making widgets for settings tab start and stop
            self.alltabdata[curtabnum]["tabwidgets"]["start"] = QPushButton("Start")
            self.alltabdata[curtabnum]["tabwidgets"]["start"].clicked.connect(
                self.startprocessor
            )
            self.alltabdata[curtabnum]["tabwidgets"]["stop"] = QPushButton("Stop")
            self.alltabdata[curtabnum]["tabwidgets"]["stop"].clicked.connect(
                self.stopprocessor
            )

            # data source
            self.alltabdata[curtabnum]["tabwidgets"]["chanseltitle"] = QLabel(
                "Channel select: "
            )
            self.alltabdata[curtabnum]["tabwidgets"]["chanselect"] = QComboBox()
            self.alltabdata[curtabnum]["tabwidgets"]["chanselect"].addItem(
                "No Channels"
            )
            self.alltabdata[curtabnum]["tabwidgets"][
                "chanselect"
            ].currentTextChanged.connect(self.chan_text_changed)

            self.alltabdata[curtabnum]["tabwidgets"]["subchansel"] = QComboBox()
            self.alltabdata[curtabnum]["tabwidgets"]["subchansel"].addItem(
                "No Sub Channels"
            )
            self.alltabdata[curtabnum]["tabwidgets"][
                "subchansel"
            ].currentIndexChanged.connect(self.sub_ind_changed)

            # time range
            self.alltabdata[curtabnum]["tabwidgets"]["timerangemintitle"] = QLabel(
                "Time Range Min: "
            )

            self.alltabdata[curtabnum]["tabwidgets"]["timerangemin"] = QSlider(
                Qt.Orientation.Horizontal
            )
            self.alltabdata[curtabnum]["tabwidgets"]["timerangemin"].setRange(initstats["timerangemin"], initstats["timerangemax"])
            self.alltabdata[curtabnum]["tabwidgets"]["timerangemin"].setValue(
                initstats["timerangemin"]
            )
            self.alltabdata[curtabnum]["tabwidgets"]["timerangemin"].setSingleStep(1)
            self.alltabdata[curtabnum]["tabwidgets"]["timerangemin"].setPageStep(10)

            self.alltabdata[curtabnum]["tabwidgets"]["timerangemaxtitle"] = QLabel(
                "Time Range Max: "
            )

            self.alltabdata[curtabnum]["tabwidgets"]["timerangemax"] = QSlider(
                Qt.Orientation.Horizontal
            )
            self.alltabdata[curtabnum]["tabwidgets"]["timerangemax"].setRange(initstats["timerangemin"], initstats["timerangemax"])
            self.alltabdata[curtabnum]["tabwidgets"]["timerangemax"].setValue(
                initstats["timerangemax"]
            )
            self.alltabdata[curtabnum]["tabwidgets"]["timerangemax"].setSingleStep(1)
            self.alltabdata[curtabnum]["tabwidgets"]["timerangemax"].setPageStep(10)

            t_min, t_max = self.get_datetime_bnds(initstats["timerangemin"],initstats["timerangemax"])
            self.alltabdata[curtabnum]["tabwidgets"]["timerangemintext"] = QLabel(
                t_min.isoformat()
            )
            self.alltabdata[curtabnum]["tabwidgets"]["timerangemintext"].setAlignment(
                Qt.AlignRight | Qt.AlignVCenter
            )

            self.alltabdata[curtabnum]["tabwidgets"]["timerangemaxtext"] = QLabel(
                t_max.isoformat()
            )
            self.alltabdata[curtabnum]["tabwidgets"]["timerangemaxtext"].setAlignment(
                Qt.AlignRight | Qt.AlignVCenter
            )


            # Color bar settings
            self.alltabdata[curtabnum]["tabwidgets"]["cmintitle"] = QLabel(
                "Color Minimum: "
            )
            self.alltabdata[curtabnum]["tabwidgets"]["cmintitle"].setAlignment(
                Qt.AlignRight | Qt.AlignVCenter
            )
            self.alltabdata[curtabnum]["tabwidgets"]["cmaxtitle"] = QLabel(
                "Color Maximum: "
            )
            self.alltabdata[curtabnum]["tabwidgets"]["cmaxtitle"].setAlignment(
                Qt.AlignRight | Qt.AlignVCenter
            )
            self.alltabdata[curtabnum]["tabwidgets"]["cmin"] = QDoubleSpinBox()
            self.alltabdata[curtabnum]["tabwidgets"]["cmin"].setRange(-200, 0)
            self.alltabdata[curtabnum]["tabwidgets"]["cmin"].setSingleStep(0.1)
            self.alltabdata[curtabnum]["tabwidgets"]["cmin"].setDecimals(1)
            self.alltabdata[curtabnum]["tabwidgets"]["cmin"].setValue(
                initstats["crange"][0]
            )
            self.alltabdata[curtabnum]["tabwidgets"]["cmax"] = QDoubleSpinBox()
            self.alltabdata[curtabnum]["tabwidgets"]["cmax"].setRange(-150, 0)
            self.alltabdata[curtabnum]["tabwidgets"]["cmax"].setSingleStep(0.1)
            self.alltabdata[curtabnum]["tabwidgets"]["cmax"].setDecimals(1)
            self.alltabdata[curtabnum]["tabwidgets"]["cmax"].setValue(
                initstats["crange"][1]
            )

            # FFT length fftwindow
            self.alltabdata[curtabnum]["tabwidgets"]["fftlentitle"] = QLabel(
                "FFT Window Length samples: "
            )
            self.alltabdata[curtabnum]["tabwidgets"]["fftlentitle"].setAlignment(
                Qt.AlignRight | Qt.AlignVCenter
            )
            self.alltabdata[curtabnum]["tabwidgets"]["fftlen"] = QDoubleSpinBox()
            self.alltabdata[curtabnum]["tabwidgets"]["fftlen"].setRange(32, 1048576)
            self.alltabdata[curtabnum]["tabwidgets"]["fftlen"].setSingleStep(1)
            self.alltabdata[curtabnum]["tabwidgets"]["fftlen"].setDecimals(1)
            self.alltabdata[curtabnum]["tabwidgets"]["fftlen"].setValue(initstats["fftlen"])

            # Repetition rate  dt
            self.alltabdata[curtabnum]["tabwidgets"]["ninttitle"] = QLabel(
                "Number of integrations: "
            )
            self.alltabdata[curtabnum]["tabwidgets"]["ninttitle"].setAlignment(
                Qt.AlignRight | Qt.AlignVCenter
            )
            self.alltabdata[curtabnum]["tabwidgets"]["nint"] = QDoubleSpinBox()
            self.alltabdata[curtabnum]["tabwidgets"]["nint"].setRange(1, 100000)
            self.alltabdata[curtabnum]["tabwidgets"]["nint"].setSingleStep(1)
            self.alltabdata[curtabnum]["tabwidgets"]["nint"].setDecimals(1)
            self.alltabdata[curtabnum]["tabwidgets"]["nint"].setValue(1)

            # Repetition rate  dt
            self.alltabdata[curtabnum]["tabwidgets"]["ntimetitle"] = QLabel(
                "Number of Time points in STI: "
            )
            self.alltabdata[curtabnum]["tabwidgets"]["ntimetitle"].setAlignment(
                Qt.AlignRight | Qt.AlignVCenter
            )
            self.alltabdata[curtabnum]["tabwidgets"]["ntime"] = QDoubleSpinBox()
            self.alltabdata[curtabnum]["tabwidgets"]["ntime"].setRange(100, 100000)
            self.alltabdata[curtabnum]["tabwidgets"]["ntime"].setSingleStep(1)
            self.alltabdata[curtabnum]["tabwidgets"]["ntime"].setDecimals(1)
            self.alltabdata[curtabnum]["tabwidgets"]["ntime"].setValue(100)

            # Min max frequencies
            self.alltabdata[curtabnum]["tabwidgets"]["fmintitle"] = QLabel(
                "Frequency Min (kHz): "
            )
            self.alltabdata[curtabnum]["tabwidgets"]["fmintitle"].setAlignment(
                Qt.AlignRight | Qt.AlignVCenter
            )
            self.alltabdata[curtabnum]["tabwidgets"]["fmaxtitle"] = QLabel(
                "Frequency Max (kHz): "
            )
            self.alltabdata[curtabnum]["tabwidgets"]["fmaxtitle"].setAlignment(
                Qt.AlignRight | Qt.AlignVCenter
            )
            self.alltabdata[curtabnum]["tabwidgets"]["fmin"] = QSpinBox()
            self.alltabdata[curtabnum]["tabwidgets"]["fmin"].setRange(-1000, 1000)
            self.alltabdata[curtabnum]["tabwidgets"]["fmin"].setSingleStep(1)
            self.alltabdata[curtabnum]["tabwidgets"]["fmin"].setValue(
                initstats["frange"][0]
            )
            self.alltabdata[curtabnum]["tabwidgets"]["fmax"] = QSpinBox()
            self.alltabdata[curtabnum]["tabwidgets"]["fmax"].setRange(-1000, 1000)
            self.alltabdata[curtabnum]["tabwidgets"]["fmax"].setSingleStep(1)
            self.alltabdata[curtabnum]["tabwidgets"]["fmax"].setValue(
                initstats["frange"][1]
            )

            self.alltabdata[curtabnum]["tabwidgets"]["updatesettings"] = QPushButton(
                "Update Settings"
            )
            self.alltabdata[curtabnum]["tabwidgets"]["updatesettings"].clicked.connect(
                self.updatecurtabsettings
            )

            ctext = self.getspecs()
            self.alltabdata[curtabnum]["tabwidgets"]["specs"] = QLabel(ctext)

            widget_layout = {
                "start": {"wrows": 1, "wcols": 1, "wrext": 1, "wcolext": 1},
                "stop": {"wrows": 1, "wcols": 2, "wrext": 1, "wcolext": 1},
                "chanseltitle": {"wrows": 2, "wcols": 1, "wrext": 1, "wcolext": 2},
                "chanselect": {"wrows": 3, "wcols": 1, "wrext": 1, "wcolext": 2},
                "subchansel": {"wrows": 4, "wcols": 1, "wrext": 1, "wcolext": 2},
                "timerangemintitle": {"wrows": 5, "wcols": 1, "wrext": 1, "wcolext": 1},
                "timerangemintext": {"wrows": 5, "wcols": 2, "wrext": 1, "wcolext": 1},
                "timerangemin": {"wrows": 6, "wcols": 1, "wrext": 1, "wcolext": 2},
                "timerangemaxtitle": {"wrows": 7, "wcols": 1, "wrext": 1, "wcolext": 1},
                "timerangemaxtext": {"wrows": 7, "wcols": 2, "wrext": 1, "wcolext": 1},
                "timerangemax": {"wrows": 8, "wcols": 1, "wrext": 1, "wcolext": 2},
                "cmintitle": {"wrows": 2, "wcols": 3, "wrext": 1, "wcolext": 1},
                "cmin": {"wrows": 2, "wcols": 4, "wrext": 1, "wcolext": 1},
                "cmaxtitle": {"wrows": 3, "wcols": 3, "wrext": 1, "wcolext": 1},
                "cmax": {"wrows": 3, "wcols": 4, "wrext": 1, "wcolext": 1},
                "fftlentitle": {"wrows": 4, "wcols": 3, "wrext": 1, "wcolext": 1},
                "fftlen": {"wrows": 4, "wcols": 4, "wrext": 1, "wcolext": 1},
                "ninttitle": {"wrows": 5, "wcols": 3, "wrext": 1, "wcolext": 1},
                "nint": {"wrows": 5, "wcols": 4, "wrext": 1, "wcolext": 1},
                "ntimetitle": {"wrows": 6, "wcols": 3, "wrext": 1, "wcolext": 1},
                "ntime": {"wrows": 6, "wcols": 4, "wrext": 1, "wcolext": 1},
                "updatesettings": {"wrows": 1, "wcols": 5, "wrext": 1, "wcolext": 2},
                "specs": {"wrows": 2, "wcols": 5, "wrext": 3, "wcolext": 2},
                "fmintitle": {"wrows": 5, "wcols": 5, "wrext": 1, "wcolext": 1},
                "fmin": {"wrows": 5, "wcols": 6, "wrext": 1, "wcolext": 1},
                "fmaxtitle": {"wrows": 6, "wcols": 5, "wrext": 1, "wcolext": 1},
                "fmax": {"wrows": 6, "wcols": 6, "wrext": 1, "wcolext": 1},
            }

            for i, d1 in widget_layout.items():
                widmain = self.alltabdata[curtabnum]["tabwidgets"][i]
                self.alltabdata[curtabnum]["mainsettingslayout"].addWidget(
                    widmain, d1["wrows"], d1["wcols"], d1["wrext"], d1["wcolext"]
                )

            # adjusting stretch factors for all rows/columns
            colstretch = [0, 1, 1, 1, 1, 1, 1, 0]
            for col, cstr in zip(range(0, len(colstretch)), colstretch):
                self.alltabdata[curtabnum]["mainsettingslayout"].setColumnStretch(
                    col, cstr
                )
            rowstretch = [2, 1, 1, 1, 1, 1, 1, 4]
            for row, rstr in zip(range(0, len(rowstretch)), rowstretch):
                self.alltabdata[curtabnum]["mainsettingslayout"].setRowStretch(
                    row, rstr
                )

            # making widgets for file saving tab
            self.alltabdata[curtabnum]["tabwidgets"]["savetitle"] = QLabel("Save: ")

            self.alltabdata[curtabnum]["tabwidgets"]["savespectro"] = QCheckBox(
                "Save spectrogram"
            )
            self.alltabdata[curtabnum]["tabwidgets"]["savespectro"].clicked.connect(
                self.updatesavespectrobox
            )
            self.alltabdata[curtabnum]["tabwidgets"]["savefile"] = QPushButton(
                "Save File(s)"
            )
            self.alltabdata[curtabnum]["tabwidgets"]["savefile"].clicked.connect(
                self.savefiles
            )

            self.alltabdata[curtabnum]["tabwidgets"]["timerangetitle"] = QLabel(
                "Time range to save:"
            )
            self.alltabdata[curtabnum]["tabwidgets"]["savesubset"] = QCheckBox(
                "Save subset"
            )
            self.alltabdata[curtabnum]["tabwidgets"]["savesubset"].clicked.connect(
                self.updatesavesubsetbox
            )

            self.alltabdata[curtabnum]["tabwidgets"]["starttimetitle"] = QLabel(
                "Start Time: "
            )
            self.alltabdata[curtabnum]["tabwidgets"]["starttimetitle"].setAlignment(
                Qt.AlignRight | Qt.AlignVCenter
            )
            self.alltabdata[curtabnum]["tabwidgets"]["starttime"] = QDoubleSpinBox()
            self.alltabdata[curtabnum]["tabwidgets"]["starttime"].setRange(0, 0)
            self.alltabdata[curtabnum]["tabwidgets"]["starttime"].setSingleStep(0.05)
            self.alltabdata[curtabnum]["tabwidgets"]["starttime"].setDecimals(2)
            self.alltabdata[curtabnum]["tabwidgets"]["starttime"].setValue(0)
            self.alltabdata[curtabnum]["tabwidgets"]["endtimetitle"] = QLabel(
                "End Time: "
            )
            self.alltabdata[curtabnum]["tabwidgets"]["endtimetitle"].setAlignment(
                Qt.AlignRight | Qt.AlignVCenter
            )
            self.alltabdata[curtabnum]["tabwidgets"]["endtime"] = QDoubleSpinBox()
            self.alltabdata[curtabnum]["tabwidgets"]["endtime"].setRange(0, 0)
            self.alltabdata[curtabnum]["tabwidgets"]["endtime"].setSingleStep(0.05)
            self.alltabdata[curtabnum]["tabwidgets"]["endtime"].setDecimals(2)
            self.alltabdata[curtabnum]["tabwidgets"]["endtime"].setValue(0)

            self.alltabdata[curtabnum]["tabwidgets"]["spectrosettingstitle"] = QLabel(
                "Spectrogram Settings: "
            )
            self.alltabdata[curtabnum]["tabwidgets"]["savecmintitle"] = QLabel(
                "Color Min: "
            )
            self.alltabdata[curtabnum]["tabwidgets"]["savecmintitle"].setAlignment(
                Qt.AlignRight | Qt.AlignVCenter
            )
            self.alltabdata[curtabnum]["tabwidgets"]["savecmaxtitle"] = QLabel(
                "Color Max: "
            )
            self.alltabdata[curtabnum]["tabwidgets"]["savecmaxtitle"].setAlignment(
                Qt.AlignRight | Qt.AlignVCenter
            )
            self.alltabdata[curtabnum]["tabwidgets"]["savecmin"] = QDoubleSpinBox()
            self.alltabdata[curtabnum]["tabwidgets"]["savecmin"].setRange(0.0, 299.9)
            self.alltabdata[curtabnum]["tabwidgets"]["savecmin"].setSingleStep(0.1)
            self.alltabdata[curtabnum]["tabwidgets"]["savecmin"].setDecimals(1)
            self.alltabdata[curtabnum]["tabwidgets"]["savecmin"].setValue(
                initstats["crange"][0]
            )
            self.alltabdata[curtabnum]["tabwidgets"]["savecmax"] = QDoubleSpinBox()
            self.alltabdata[curtabnum]["tabwidgets"]["savecmax"].setRange(0.1, 300)
            self.alltabdata[curtabnum]["tabwidgets"]["savecmax"].setSingleStep(0.1)
            self.alltabdata[curtabnum]["tabwidgets"]["savecmax"].setDecimals(1)
            self.alltabdata[curtabnum]["tabwidgets"]["savecmax"].setValue(
                initstats["crange"][1]
            )

            self.alltabdata[curtabnum]["tabwidgets"]["savefmintitle"] = QLabel(
                "Frequency Min (kHz): "
            )
            self.alltabdata[curtabnum]["tabwidgets"]["savefmintitle"].setAlignment(
                Qt.AlignRight | Qt.AlignVCenter
            )
            self.alltabdata[curtabnum]["tabwidgets"]["savefmaxtitle"] = QLabel(
                "Frequency Max (kHz): "
            )
            self.alltabdata[curtabnum]["tabwidgets"]["savefmaxtitle"].setAlignment(
                Qt.AlignRight | Qt.AlignVCenter
            )
            self.alltabdata[curtabnum]["tabwidgets"]["savefmin"] = QSpinBox()
            self.alltabdata[curtabnum]["tabwidgets"]["savefmin"].setRange(0, 49999)
            self.alltabdata[curtabnum]["tabwidgets"]["savefmin"].setSingleStep(1)
            self.alltabdata[curtabnum]["tabwidgets"]["savefmin"].setValue(
                initstats["frange"][0]
            )
            self.alltabdata[curtabnum]["tabwidgets"]["savefmax"] = QSpinBox()
            self.alltabdata[curtabnum]["tabwidgets"]["savefmax"].setRange(0, 50000)
            self.alltabdata[curtabnum]["tabwidgets"]["savefmax"].setSingleStep(1)
            self.alltabdata[curtabnum]["tabwidgets"]["savefmax"].setValue(
                initstats["frange"][1]
            )

            self.alltabdata[curtabnum]["tabwidgets"]["savespectro"].setChecked(True)
            self.updatesavespectrobox(True)
            self.alltabdata[curtabnum]["tabwidgets"]["savesubset"].setChecked(False)
            self.updatesavesubsetbox(False)

            widget_layout = {
                "savetitle": {"wrows": 1, "wcols": 1, "wrext": 1, "wcolext": 1},
                "savespectro": {"wrows": 3, "wcols": 1, "wrext": 1, "wcolext": 1},
                "savefile": {"wrows": 4, "wcols": 1, "wrext": 1, "wcolext": 1},
                "timerangetitle": {"wrows": 1, "wcols": 3, "wrext": 1, "wcolext": 2},
                "savesubset": {"wrows": 2, "wcols": 3, "wrext": 1, "wcolext": 2},
                "starttimetitle": {"wrows": 3, "wcols": 3, "wrext": 1, "wcolext": 1},
                "starttime": {"wrows": 3, "wcols": 4, "wrext": 1, "wcolext": 1},
                "endtimetitle": {"wrows": 4, "wcols": 3, "wrext": 1, "wcolext": 1},
                "endtime": {"wrows": 4, "wcols": 4, "wrext": 1, "wcolext": 1},
                "spectrosettingstitle": {
                    "wrows": 1,
                    "wcols": 6,
                    "wrext": 1,
                    "wcolext": 2,
                },
                "savecmintitle": {"wrows": 2, "wcols": 6, "wrext": 1, "wcolext": 1},
                "savecmin": {"wrows": 2, "wcols": 7, "wrext": 1, "wcolext": 1},
                "savecmaxtitle": {"wrows": 3, "wcols": 6, "wrext": 1, "wcolext": 1},
                "savecmax": {"wrows": 3, "wcols": 7, "wrext": 1, "wcolext": 1},
                "savefmintitle": {"wrows": 4, "wcols": 6, "wrext": 1, "wcolext": 1},
                "savefmin": {"wrows": 4, "wcols": 7, "wrext": 1, "wcolext": 1},
                "savefmaxtitle": {"wrows": 5, "wcols": 6, "wrext": 1, "wcolext": 1},
                "savefmax": {"wrows": 5, "wcols": 7, "wrext": 1, "wcolext": 1},
            }

            for i, d1 in widget_layout.items():
                widmain = self.alltabdata[curtabnum]["tabwidgets"][i]
                self.alltabdata[curtabnum]["plotsavelayout"].addWidget(
                    widmain, d1["wrows"], d1["wcols"], d1["wrext"], d1["wcolext"]
                )

            # adjusting stretch factors for all rows/columns
            colstretch = [6, 4, 1, 2, 2, 1, 2, 2, 6]
            for col, cstr in zip(range(0, len(colstretch)), colstretch):
                self.alltabdata[curtabnum]["plotsavelayout"].setColumnStretch(col, cstr)
            rowstretch = [3, 1, 1, 1, 1, 1, 5]
            for row, rstr in zip(range(0, len(rowstretch)), rowstretch):
                self.alltabdata[curtabnum]["plotsavelayout"].setRowStretch(row, rstr)

            ##making the current layout for the tab
            self.alltabdata[curtabnum]["tab"].setLayout(
                self.alltabdata[curtabnum]["mainLayout"]
            )

        except Exception:  # if something breaks
            trace_error()
            self.posterror("Failed to build new tab")

    # =============================================================================
    #       Plot update and control, signal processor interactions
    # =============================================================================

    def chan_text_changed(self, str_in):
        """Control function for channel combo box to change channel and record it.

        Parameters
        ----------
        str_in : str
            String for the channel name.
        """
        curtabnum, _ = self.whatTab()
        if str_in in  list(self.alltabdata[curtabnum]["stats"]["chandict"].keys()):
            self.alltabdata[curtabnum]["stats"]["chanselect"] = str_in
            sub_chanlist = self.alltabdata[curtabnum]["stats"]["chandict"][str_in]
            self.alltabdata[curtabnum]["tabwidgets"]["subchansel"].clear()
            self.alltabdata[curtabnum]["stats"]["subchansel"] = sub_chanlist[0]
            for isub in sub_chanlist:
                self.alltabdata[curtabnum]["tabwidgets"]["subchansel"].addItem(str(isub))

    def sub_ind_changed(self, index):
        """Control function for subchannel combox box to change sub channel and record it.

        Parameters
        ----------
        index : int
            integer for the sub channel.
        """
        curtabnum, _ = self.whatTab()
        self.alltabdata[curtabnum]["stats"]["subchansel"] = index

    def getspecs(self):
        """Updates to the text on the info on the specs

        Returns
        -------
        text : str
            Info string for the data set.
        """
        curtabnum, _ = self.whatTab()
        stats = self.alltabdata[curtabnum]["stats"]

        fsnunits = "kHz"

        if stats["updated"]:
            fs = stats["sr"]
            nfft = stats["fftlen"]
            df = int(fs/nfft)

            if fs > 1000:
                fsnunits = "kHz"
                fs /= 1000

            fn = fs / 2

        else:
            fs = fn = df = nfft = "TBD"

        text = f"Specifications: \nSampling Frequency {fs} {fsnunits}\nNyquist Frequency {fn} {fsnunits}\nNFFT: {nfft}\nFrequency Resolution: {df} Hz"
        return text


    def get_datetime_bnds(self,tmin,tmax):
        """Returns the bounds given from the slider in datetime format.
        
        Parameters
        ----------
        tmin : int
            Lower bound set by the slider.
        tmax : int
            Upper bound set by the slider.

        Returns
        -------
        dt_st : datetime
            Desired start time in datetime format.
        dt_et : datetime
            Desired end time in datetime format.
        """
        curtabnum, _ = self.whatTab()
        if self.alltabdata[curtabnum]["Processor"] is None:
            return drf.util.sample_to_datetime(int(1451661840),1),drf.util.sample_to_datetime(int(1451665440),1)
        
        min_part = tmin
        max_part = tmax

        bnds = self.alltabdata[curtabnum]["Processor"].drfIn.time_bnds
        bnds_ext = bnds[1]-bnds[0]
        tab_wid_ext = 10000
        des_st = (min_part * bnds_ext) / tab_wid_ext + bnds[0]
        des_end = (max_part * bnds_ext) / tab_wid_ext + bnds[0]
        return drf.util.sample_to_datetime(int(des_st),1),drf.util.sample_to_datetime(int(des_end),1)


    def updatecurtabsettings(self):
        """This calls pullsettings which updates """
        curtabnum, _ = self.whatTab()
        self.pullsettings(curtabnum, True)

    def pullsettings(self, curtabnum, updateProcessor):

        # get the time settings
        self.alltabdata[curtabnum]["stats"]["timerangemin"] = self.alltabdata[
            curtabnum
        ]["tabwidgets"]["timerangemin"].value()

        self.alltabdata[curtabnum]["stats"]["timerangemax"] = self.alltabdata[
            curtabnum
        ]["tabwidgets"]["timerangemax"].value()

        # translate the sliders to datetime and then to a timestamp 
        dt_b,dt_e = self.get_datetime_bnds(self.alltabdata[curtabnum]["stats"]["timerangemin"], self.alltabdata[curtabnum]["stats"]["timerangemax"])
        new_tmin = drf.util.datetime_to_timestamp(dt_b)
        new_tmax = drf.util.datetime_to_timestamp(dt_e)

        # Color range
        oldcrange = self.alltabdata[curtabnum]["stats"]["crange"]
        self.alltabdata[curtabnum]["stats"]["crange"] = [
            self.alltabdata[curtabnum]["tabwidgets"]["cmin"].value(),
            self.alltabdata[curtabnum]["tabwidgets"]["cmax"].value(),
        ]
        if (
            self.alltabdata[curtabnum]["stats"]["crange"][1]
            <= self.alltabdata[curtabnum]["stats"]["crange"][0]
        ):
            self.alltabdata[curtabnum]["stats"]["crange"] = oldcrange
            self.alltabdata[curtabnum]["tabwidgets"]["cmin"].setValue(oldcrange[0])
            self.alltabdata[curtabnum]["tabwidgets"]["cmax"].setValue(oldcrange[1])
            self.postwarning("Maximum color range must exceed minimum value!")


        oldfrange = self.alltabdata[curtabnum]["stats"]["frange"]
        self.alltabdata[curtabnum]["stats"]["frange"] = [
            self.alltabdata[curtabnum]["tabwidgets"]["fmin"].value(),
            self.alltabdata[curtabnum]["tabwidgets"]["fmax"].value(),
        ]
        if (
            self.alltabdata[curtabnum]["stats"]["frange"][1]
            <= self.alltabdata[curtabnum]["stats"]["frange"][0]
        ):
            self.alltabdata[curtabnum]["stats"]["frange"] = oldcrange
            self.alltabdata[curtabnum]["tabwidgets"]["fmin"].setValue(oldfrange[0])
            self.alltabdata[curtabnum]["tabwidgets"]["fmax"].setValue(oldfrange[1])
            self.postwarning("Maximum frequency range must exceed minimum value!")
        # channel
        self.alltabdata[curtabnum]["stats"]["chanselect"] = self.alltabdata[curtabnum][
            "tabwidgets"
        ]["chanselect"].currentText()
        # Info for spectrogram
        self.alltabdata[curtabnum]["stats"]["nint"] = self.alltabdata[curtabnum][
            "tabwidgets"
        ]["nint"].value()
        self.alltabdata[curtabnum]["stats"]["ntime"] = self.alltabdata[curtabnum][
            "tabwidgets"
        ]["ntime"].value()
        self.alltabdata[curtabnum]["stats"]["fftlen"] = self.alltabdata[curtabnum][
            "tabwidgets"
        ]["fftlen"].value()

        self.updateAxesLimits(curtabnum)
        self.updatecolorbar(curtabnum, self.alltabdata[curtabnum]["stats"]["crange"])

        if self.alltabdata[curtabnum]["isprocessing"] and updateProcessor:
            self.alltabdata[curtabnum]["Processor"].updatesettings_slot(
                self.alltabdata[curtabnum]["stats"]["fftlen"],
                self.alltabdata[curtabnum]["stats"]["nint"],
                self.alltabdata[curtabnum]["stats"]["ntime"],
                new_tmin,
                new_tmax,
            )

        # updating QLabel with signal processing specs
        ctext = self.getspecs()
        self.alltabdata[curtabnum]["tabwidgets"]["specs"].setText(ctext)

        # updating color and frequency ranges on save plot
        self.alltabdata[curtabnum]["tabwidgets"]["savecmin"].setValue(
            self.alltabdata[curtabnum]["stats"]["crange"][0]
        )
        self.alltabdata[curtabnum]["tabwidgets"]["savecmax"].setValue(
            self.alltabdata[curtabnum]["stats"]["crange"][1]
        )
        self.alltabdata[curtabnum]["tabwidgets"]["savefmin"].setValue(
            self.alltabdata[curtabnum]["stats"]["frange"][0]
        )
        self.alltabdata[curtabnum]["tabwidgets"]["savefmax"].setValue(
            self.alltabdata[curtabnum]["stats"]["frange"][1]
        )

    @pyqtSlot(int, Fraction, int, float, int, tuple)
    def updatesettingsfromprocessor(
        self, tabID, sr,fftbins, n_int,n_time,time_limss
    ):  # TODO: SORT OUT FMIN AND FMAX STUFF + FREQUENCY TRIMMING!!!
        curtabnum = self.tabnumbers.index(tabID)
        self.alltabdata[curtabnum]["stats"]["updated"] = True
        self.alltabdata[curtabnum]["stats"]['fftlen'] = fftbins
        self.alltabdata[curtabnum]["stats"]['nint'] = n_int
        self.alltabdata[curtabnum]["stats"]['ntime'] = n_time
        self.alltabdata[curtabnum]["data"]['timebnds'] = time_limss
 

        self.alltabdata[curtabnum]["stats"]["sr"] = sr
        freqs = np.fft.fftshift(np.fft.fftfreq(fftbins, float(1/sr)))
        self.alltabdata[curtabnum]["stats"]["freqs"] = freqs
        self.alltabdata[curtabnum]["data"]["freqs"] = freqs

        minF = int(np.min(freqs)*1e-3)
        maxF = int(np.max(freqs)*1e-3)
        self.alltabdata[curtabnum]["tabwidgets"]["fmin"].setRange(minF, maxF)
        self.alltabdata[curtabnum]["tabwidgets"]["fmax"].setRange(minF, maxF)
        self.alltabdata[curtabnum]["tabwidgets"]["savefmin"].setRange(minF, maxF)
        self.alltabdata[curtabnum]["tabwidgets"]["savefmax"].setRange(minF, maxF)
        if self.alltabdata[curtabnum]["stats"]["frange"][0] < minF:
            self.alltabdata[curtabnum]["stats"]["frange"][0] = minF
            self.alltabdata[curtabnum]["tabwidgets"]["fmin"].setValue(minF)
        if self.alltabdata[curtabnum]["stats"]["frange"][1] > maxF:
            self.alltabdata[curtabnum]["stats"]["frange"][1] = maxF
            self.alltabdata[curtabnum]["tabwidgets"]["fmax"].setValue(maxF)
        cfrange = self.alltabdata[curtabnum]["stats"]["frange"]

        keepvals = np.all(
            (np.greater_equal(freqs, 1e3*cfrange[0]), np.less_equal(freqs, 1e3*cfrange[1])),
            axis=0,
        )
        freqs = freqs[keepvals]
        inds = np.argwhere(keepvals)
        fscale = int(np.ceil(len(freqs) / self.maxNfreqs))
        self.alltabdata[curtabnum]["stats"]["fscale"] = fscale
        relplotindices = range(int(np.floor(fscale / 2)), len(freqs), fscale)
        self.alltabdata[curtabnum]["stats"]["plotindices"] = [
            inds[i][0] for i in relplotindices
        ]
        self.alltabdata[curtabnum]["data"]["plotfreqs"] = [
            freqs[i] for i in relplotindices
        ]
        self.pullsettings(
            curtabnum, False
        )  # dont update processor to prevent recursion

    def gencolorbar(self, curtabnum, crange):

        self.cdata = np.array(
            cm.viridis.colors
        )  # np.genfromtxt('spectralcolors.txt',delimiter=',')
        self.npoints = self.cdata.shape[0]  # number of colors
        self.spectralmap = ListedColormap(
            np.append(self.cdata, np.ones((np.shape(self.cdata)[0], 1)), axis=1)
        )
        cbar_cm_object = self.buildspectrogramcolorbar(
            self.spectralmap,
            crange,
            self.alltabdata[curtabnum]["SpectroFig"],
            self.alltabdata[curtabnum]["SpectroAxes"],
        )
        self.alltabdata[curtabnum]["SpectroCanvas"].draw()
        self.levels = np.linspace(crange[0], crange[1], self.npoints)

        return cbar_cm_object

    def updatecolorbar(self, curtabnum, crange):
        self.alltabdata[curtabnum]["colorbar"].set_clim(crange[0], crange[1])
        self.levels = np.linspace(crange[0], crange[1], self.npoints)
        self.alltabdata[curtabnum]["SpectroCanvas"].draw()

    def updateAxesLimits(self, curtabnum):
        time_min = self.alltabdata[curtabnum]["stats"]["timerangemin"]
        time_max = self.alltabdata[curtabnum]["stats"]["timerangemax"]
        dt_b, dt_e = self.get_datetime_bnds(time_min,time_max)
        frange = self.alltabdata[curtabnum]["stats"]["frange"]
        if dt_b ==dt_e:
            ipdb.set_trace()
        self.alltabdata[curtabnum]["SpectroAxes"].set_ylim(dt_b, dt_e)
        self.alltabdata[curtabnum]["SpectroAxes"].set_xlim(frange[0], frange[1])
        self.alltabdata[curtabnum]["SpectroCanvas"].draw()

    def startprocessor(self):
        import traceback

        if self.threadpool.activeThreadCount() + 1 > self.threadpool.maxThreadCount():
            self.postwarning(
                "The maximum number of simultaneous processing threads has been exceeded. This processor will automatically begin collecting data when STOP is selected on another tab."
            )

        else:
            curtabnum, tabID = self.whatTab()
            self.pullsettings(
                curtabnum, False
            )  # don't need to update processor because it hasn't been initialized yet

            # curchan = self.alltabdata[curtabnum]["tabwidgets"][
            #     "chanselect"
            # ].currentText()

            fpath = Path(__file__)
            curpath = fpath.parent
            saved_path = curpath.joinpath("old_dir.txt")
            if saved_path.exists():

                with open(saved_path) as f:
                    lines = f.readlines()
                st_dir = lines[0]

            else:
                st_dir = str(Path("~").expanduser())

            drf_sel = True

            while drf_sel:

                drfdir = QFileDialog.getExistingDirectory(
                    self, "Select a Digital RF Data Set", st_dir
                )
                if not Path(drfdir).exists():
                    print("Directory does not exist, select again.")
                else:
                    try:
                        _ = drf.DigitalRFReader(drfdir)
                        drf_sel = False
                    except ValueError:
                        print("Please select a valid digital RF dataset.")

            try:
                self.initiate_processor(tabID, drfdir)
            except Exception as e:
                print("Failed to open drf directory")
                print(e)
                traceback.print_exc()

    # slot in main program to close window (only one channel selector window can be open at a time)
    @pyqtSlot(int, int, str)
    def audioWindowClosed(self, wasGood, tabID, datasource):
        if wasGood:
            self.audioWindowOpened = False
            self.initiate_processor(tabID, datasource)

    def initiate_processor(self, tabID, drf_directory):
        """This is called by start processor and does the work of calling .
        
        
        """
        curtabnum = self.tabnumbers.index(tabID)

        # making datasource QComboBox un-selectable so source can't be changed after processing initiated
        self.alltabdata[curtabnum]["tabwidgets"]["chanselect"].setEnabled(False)

        # data relevant for thread
        fftlen = self.alltabdata[curtabnum]["stats"]["fftlen"]
        nint = self.alltabdata[curtabnum]["stats"]["nint"]
        ntime = self.alltabdata[curtabnum]["stats"]["ntime"]

        self.alltabdata[curtabnum]["stats"]["updateint"] = int(
            np.ceil(1 / ntime)
        )  # updates visual once every second for live audio

        # saving datasource
        self.alltabdata[curtabnum]["datasource"] = drf_directory

        # initializing and starting thread
        self.alltabdata[curtabnum]["Processor"] = dp.DrfProcessor(
            self.usetype, drf_directory, tabID, fftlen, nint, ntime
        )


        self.alltabdata[curtabnum]["stats"]["chandict"] = self.alltabdata[curtabnum][
            "Processor"
        ].drfIn.chan_2sub
        chan_list = self.alltabdata[curtabnum]["Processor"].chan_listing
        self.threadpool.start(self.alltabdata[curtabnum]["Processor"])

        self.alltabdata[curtabnum]["tabwidgets"]["chanselect"].clear()
        
        for ichan in chan_list:
            self.alltabdata[curtabnum]["tabwidgets"]["chanselect"].addItem(ichan)

        sub_chanlist = self.alltabdata[curtabnum]["stats"]["chandict"][chan_list[0]]
        self.alltabdata[curtabnum]["tabwidgets"]["subchansel"].clear()
        # ipdb.set_trace()
        self.alltabdata[curtabnum]["stats"]["subchansel"] = sub_chanlist[0]
        for isub in sub_chanlist:
            self.alltabdata[curtabnum]["tabwidgets"]["subchansel"].addItem(str(isub))


        # connecting slots
        self.alltabdata[curtabnum]["Processor"].signals.iterated.connect(
            self.updateUIinfo
        )
        self.alltabdata[curtabnum]["Processor"].signals.statsupdated.connect(
            self.updatesettingsfromprocessor
        )
        self.alltabdata[curtabnum]["Processor"].signals.terminated.connect(
            self.updateUIfinal
        )
        self.alltabdata[curtabnum]["isprocessing"] = True
        self.alltabdata[curtabnum]["tabwidgets"]["start"].setEnabled(False)
        self.alltabdata[curtabnum]["tabwidgets"]["chanselect"].setEnabled(True)

    def stopprocessor(self):
        curtabnum, _ = self.whatTab()
        if self.alltabdata[curtabnum]["isprocessing"]:
            self.alltabdata[curtabnum]["Processor"].abort()
            self.alltabdata[curtabnum]["isprocessing"] = False

    def append_spectral_data(self, mainspectra, newspectra, trimData, fsc, inds):

        # trimming new spectra
        if trimData:
            lenspec = len(newspectra)
            newspectra_cut = np.array([])
            for i in inds:
                sind = int(np.max([0, i - fsc]))

                eind = int(np.min([lenspec, i + fsc]))
                newspectra_cut = np.append(
                    newspectra_cut, np.max(newspectra[sind:eind])
                )
        else:
            newspectra_cut = newspectra

        if mainspectra.shape == (1, 0):
            output = np.rot90(np.array([newspectra_cut]), 1)
        else:
            output = np.append(
                mainspectra, np.rot90(np.array([newspectra_cut]), 1), axis=1
            )
        return output

    @pyqtSlot(int, int, np.ndarray, np.ndarray, np.ndarray, np.ndarray)
    def updateUIinfo(
        self, i, tabID, time_ar, freqs_all, sxx, sxx_med
    ):  # TODO: configure PyQtSlot to receive data from processor thread and update spectrogram
        curtabnum = self.tabnumbers.index(tabID)

        # saving data
        self.alltabdata[curtabnum]["data"]["spectra"] = sxx
        self.alltabdata[curtabnum]["data"]["spectamed"] = sxx_med
        self.alltabdata[curtabnum]["stats"]["freqs"] = freqs_all
        self.alltabdata[curtabnum]["data"]["freqs"] = freqs_all
        self.alltabdata[curtabnum]["data"]["times"] = time_ar

        self.update_plot(curtabnum)

    def update_plot(self,curtabnum):
        plotspectra = self.alltabdata[curtabnum]["data"]["spectra"]
        crange = self.alltabdata[curtabnum]["stats"]["crange"]
        pltfreqs = self.alltabdata[curtabnum]["data"]["plotfreqs"]
        fvec = self.alltabdata[curtabnum]["data"]["freqs"]

        times = self.alltabdata[curtabnum]["data"]["times"]
        time_min = times.min()
        time_max = times.max()
        subchan = self.alltabdata[curtabnum]["stats"]["subchansel"]
        plotspectra = plotspectra[..., subchan]
        self.alltabdata[curtabnum]["SpectroAxes"].cla()
        self.alltabdata[curtabnum]["SpectroAxes"].pcolormesh(
            fvec*1e-3,
            times,
            plotspectra.T,
            cmap="viridis",
            vmin=crange[0],
            vmax=crange[1],
        )
        extent = [fvec[0]*1e-3,fvec[-1]*1e-3,time_min,time_max]
        # self.alltabdata[curtabnum]["SpectroAxes"].imshow(plotspectra.T,cmap="viridis",aspect="auto",vmin=crange[0],vmax=crange[1],extent=extent)
        self.alltabdata[curtabnum]["SpectroAxes"].set_xlim(pltfreqs[0]*1e-3, pltfreqs[-1]*1e-3)

        self.alltabdata[curtabnum]["SpectroAxes"].set_ylim(time_min, time_max)
        self.alltabdata[curtabnum]["SpectroCanvas"].draw()
        print("Update plot")


    @pyqtSlot(int, int)
    def updateUIfinal(
        self, tabID, reason
    ):  # TODO: final plot update (error codes, etc)
        curtabnum = self.tabnumbers.index(tabID)
        curtabname = self.tabWidget.tabText(curtabnum)

        self.alltabdata[curtabnum]["isprocessing"] = False
        self.update_plot(curtabnum)

        maxval = np.round(self.alltabdata[curtabnum]["data"]["maxtime"] * 20) / 20



        self.alltabdata[curtabnum]["tabwidget"].setTabEnabled(1, True)
        self.alltabdata[curtabnum]["tabwidgets"]["starttime"].setRange(0, maxval - 0.5)
        self.alltabdata[curtabnum]["tabwidgets"]["starttime"].setValue(0)
        self.alltabdata[curtabnum]["tabwidgets"]["endtime"].setRange(0, maxval)
        self.alltabdata[curtabnum]["tabwidgets"]["endtime"].setValue(maxval)

        if reason:
            if reason == 1:
                issue = "Unable to find selected audio file!"
            elif reason == 2:
                issue = "Unable to access selected audio device!"
            elif reason == 3:
                issue = "Failed to initialize AudioProcessor thread (timeout)"
            elif reason == 4:
                issue = "Unidentified error during AudioProcessor event loop"
            elif reason == 5:
                issue = "Error raised during audio stream callback function!"
            errorMessage = f"Error with tab {curtabname} (tab #{curtabnum}): {issue}"
            self.posterror(errorMessage)

    # =============================================================================
    #       PLOTTING STUFF (TODO: consolidate plotting functions from realtime and spectrogram saving functions here)
    # =============================================================================

    def buildspectrogramcolorbar(self, spectralmap, crange, fig, ax):
        cbar_cm_object = cm.ScalarMappable(
            norm=Normalize(vmin=crange[0], vmax=crange[1]), cmap=spectralmap
        )
        cbar = plt.colorbar(cbar_cm_object, ax=ax)
        cbar.set_label("dBFS")
        return cbar_cm_object

    # =============================================================================
    #       FILE SAVING STUFF
    # =============================================================================

    def updatesavespectrobox(self, isChecked):
        curtabnum, _ = self.whatTab()
        self.alltabdata[curtabnum]["tabwidgets"]["savecmin"].setEnabled(isChecked)
        self.alltabdata[curtabnum]["tabwidgets"]["savecmax"].setEnabled(isChecked)
        self.alltabdata[curtabnum]["tabwidgets"]["savefmin"].setEnabled(isChecked)
        self.alltabdata[curtabnum]["tabwidgets"]["savefmax"].setEnabled(isChecked)

    def updatesavesubsetbox(self, isChecked):
        curtabnum, _ = self.whatTab()
        self.alltabdata[curtabnum]["tabwidgets"]["starttime"].setEnabled(isChecked)
        self.alltabdata[curtabnum]["tabwidgets"]["endtime"].setEnabled(isChecked)

    def savefiles(self):

        curtabnum, tabID = self.whatTab()

        # getting data
        saveSpectro = self.alltabdata[curtabnum]["tabwidgets"][
            "savespectro"
        ].isChecked()

        savesubset = self.alltabdata[curtabnum]["tabwidgets"]["savesubset"].isChecked()
        if savesubset:
            timerange = [
                self.alltabdata[curtabnum]["tabwidgets"]["starttime"].value(),
                self.alltabdata[curtabnum]["tabwidgets"]["endtime"].value(),
            ]
        else:
            timerange = [0, self.alltabdata[curtabnum]["data"]["maxtime"]]

        colorrange = [
            self.alltabdata[curtabnum]["tabwidgets"]["savecmin"].value(),
            self.alltabdata[curtabnum]["tabwidgets"]["savecmax"].value(),
        ]
        freqrange = [
            self.alltabdata[curtabnum]["tabwidgets"]["savefmin"].value(),
            self.alltabdata[curtabnum]["tabwidgets"]["savefmax"].value(),
        ]

        if saveSpectro:
            # file dialog box to save spectrogram
            spectrofilename = self.getFileSaveSelection(
                "Spectrogram (PNG)", "Image (*.png)"
            )

        # saving files (sets spinning cursor while saving)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        if saveSpectro and spectrofilename:
            self.saveSpectroFile(
                spectrofilename, curtabnum, timerange, freqrange, colorrange
            )
        QApplication.restoreOverrideCursor()

    def saveSpectroFile(self, filename, curtabnum, timerange, freqrange, colorrange):
        if filename[-4:].lower() != ".png":
            filename += ".png"

        freqs = self.alltabdata[curtabnum]["data"]["freqs"]  # pulling data to plot
        times = self.alltabdata[curtabnum]["data"]["times"]
        spectra = self.alltabdata[curtabnum]["data"]["spectra"]

        # trimming data
        keepfreqs = np.all(
            (np.greater_equal(freqs, freqrange[0]), np.less_equal(freqs, freqrange[1])),
            axis=0,
        )
        keeptimes = np.all(
            (np.greater_equal(times, timerange[0]), np.less_equal(times, timerange[1])),
            axis=0,
        )
        freqs = freqs[keepfreqs]
        times = times[keeptimes]
        spectra = spectra[np.ix_(keepfreqs, keeptimes)]

        # calculating pixel extent for plt.imshow()

        # making figure
        fig = plt.figure()
        fig.clear()
        fig.set_size_inches(8, 4)
        ax = fig.add_axes([0.1, 0.15, 0.9, 0.80])

        # adding colorbar to plot
        self.buildspectrogramcolorbar(self.spectralmap, colorrange, fig, ax)

        # adding data to plot
        spectra[spectra < colorrange[0]] = colorrange[0]
        spectra[spectra > colorrange[1]] = colorrange[1]
        levels = np.linspace(colorrange[0], colorrange[1], len(self.cdata))
        ax.contourf(times, freqs, spectra, levels=levels, colors=self.cdata)

        # formatting
        ax.set_ylabel("Time (s)")
        ax.set_xlabel("Frequency (kHz)")
        ax.set_xlim(freqrange[0], freqrange[1])
        ax.set_ylim(timerange[0], timerange[1])

        # saving figure
        fig.savefig(filename, format="png", dpi=300)

    def getFileSaveSelection(self, filekind, fileext):
        try:
            savefile = str(
                QFileDialog.getSaveFileName(
                    self,
                    f"Select {filekind} filename to save",
                    self.defaultfiledir,
                    fileext,
                    options=QFileDialog.DontUseNativeDialog,
                )
            )
            # checking directory validity
            if savefile == "":
                return False
            else:
                return (
                    savefile.replace("(", ",").replace(")", ",").split(",")[1][1:-1]
                )  # returning just the selected filename

        except:
            trace_error()
            self.posterror("Error raised in directory selection")
            return False

    # =============================================================================
    #     TAB MANIPULATION OPTIONS, OTHER GENERAL FUNCTIONS
    # =============================================================================

    # handles tab indexing
    def addnewtab(self):
        # creating numeric ID for newly opened tab
        self.totaltabs += 1
        self.tabnumbers.append(self.totaltabs)
        newtabnum = self.tabWidget.count()
        return newtabnum

    # gets index of open tab in GUI
    def whatTab(self):
        curtabnum = self.tabWidget.currentIndex()
        return curtabnum, self.tabnumbers[curtabnum]

    # renames tab (only user-visible name, not self.alltabdata dict key)
    def renametab(self):
        try:
            curtabnum, _ = self.whatTab()
            name, ok = QInputDialog.getText(
                self,
                "Rename Current Tab",
                "Enter new tab name:",
                QLineEdit.Normal,
                str(self.tabWidget.tabText(curtabnum)),
            )
            if ok:
                self.tabWidget.setTabText(curtabnum, name)
        except Exception:
            trace_error()
            self.posterror("Failed to rename the current tab")

    # sets default color scheme for tabs
    def setnewtabcolor(self, tab):
        p = QPalette()
        gradient = QLinearGradient(0, 0, 0, 400)
        gradient.setColorAt(0.0, QColor(255, 253, 253))
        # gradient.setColorAt(1.0, QColor(248, 248, 255))
        gradient.setColorAt(1.0, QColor(255, 225, 225))
        p.setBrush(QPalette.Window, QBrush(gradient))
        tab.setAutoFillBackground(True)
        tab.setPalette(p)

    # closes a tab
    def closecurrenttab(self):
        try:
            reply = QMessageBox.question(
                self,
                "Message",
                "Are you sure to close the current tab?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )

            if reply == QMessageBox.Yes:

                # getting tab to close
                curtabnum, _ = self.whatTab()

                # add any additional necessary commands (stop threads, prevent memory leaks, etc) here

                # closing tab
                self.tabWidget.removeTab(curtabnum)

                # removing current tab data from the self.alltabdata dict, correcting tabnumbers variable
                self.alltabdata.pop(curtabnum)
                self.tabnumbers.pop(curtabnum)

        except Exception:
            trace_error()
            self.posterror("Failed to close the current tab")

    # warning message
    def postwarning(self, warningtext):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Warning)
        msg.setText(warningtext)
        msg.setWindowTitle("Warning")
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec_()

    # error message
    def posterror(self, errortext):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Critical)
        msg.setText(errortext)
        msg.setWindowTitle("Error")
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec_()

    # warning message with options (Okay or Cancel)
    def postwarning_option(self, warningtext):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Warning)
        msg.setText(warningtext)
        msg.setWindowTitle("Warning")
        msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        outval = msg.exec_()
        option = "unknown"
        if outval == 1024:
            option = "okay"
        elif outval == 4194304:
            option = "cancel"
        return option

    # add warning message before closing GUI
    def closeEvent(self, event):
        reply = QMessageBox.question(
            self,
            "Message",
            "Are you sure to close the application? \n All unsaved work will be lost!",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:

            # explicitly closing figures to clean up memory (should be redundant here but just in case)
            for tab in self.alltabdata:
                plt.close(tab["SpectroFig"])

                # aborting all threads
                if tab["isprocessing"]:
                    tab["Processor"].abort()

            event.accept()
        else:
            event.ignore()


# =============================================================================
#        POPUP WINDOW FOR AUDIO CHANNEL SELECTION
# =============================================================================


class AudioWindow(QWidget):

    def __init__(self, nchannels, tabID, fname):
        super(AudioWindow, self).__init__()

        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        self.selectedChannel = 1
        self.wasClosed = False
        self.nchannels = nchannels
        self.fname = fname
        self.tabID = tabID

        self.signals = AudioWindowSignals()

        self.title = QLabel(
            "Select channel to read\n(for 2-channel WAV files,\nCh1 = left and Ch2 = right):"
        )
        self.spinbox = QSpinBox()
        self.spinbox.setMinimum(1)
        self.spinbox.setMaximum(self.nchannels)
        self.spinbox.setSingleStep(1)
        self.spinbox.setValue(self.selectedChannel)
        self.finish = QPushButton("Select Channel")
        self.finish.clicked.connect(self.selectChannel)

        self.layout.addWidget(self.title)
        self.layout.addWidget(self.spinbox)
        self.layout.addWidget(self.finish)

        self.show()

    def selectChannel(self):
        self.selectedChannel = self.spinbox.value()

        # format is Audio<channel#><filename> e.g. Audio0002/My/File.WAV
        # allowing for 5-digit channels since WAV file channel is a 16-bit integer, can go to 65,536
        self.datasource = f"AAA-{self.selectedChannel:05d}-{self.fname}"

        # emit signal
        self.signals.closed.emit(True, self.tabID, self.datasource)

        # close dialogue box
        self.wasClosed = True
        self.close()

    # add warning message on exit
    def closeEvent(self, event):
        event.accept()
        if not self.wasClosed:
            self.signals.closed.emit(False, "No", "No")
            self.wasClosed = True


# initializing signals for data to be passed back to main loop
class AudioWindowSignals(QObject):
    closed = pyqtSignal(int, int, str)


# =============================================================================
#        CUSTOM AXIS TOOLBAR
# =============================================================================
# class to customize nagivation toolbar in profile editor tab to control profile plots (pan/zoom/reset view)
class CustomToolbar(NavigationToolbar):
    def __init__(self, canvas_, parent_):
        self.toolitems = (
            ("Home", "Reset Original View", "home", "home"),
            ("Back", "Go To Previous View", "back", "back"),
            ("Forward", "Return to Next View", "forward", "forward"),
            ("Pan", "Click and Drag to Pan", "move", "pan"),
            ("Zoom", "Select Region to Zoon", "zoom_to_rect", "zoom"),
            ("Save", "Save the figure", "filesave", "save_figure"),
        )
        NavigationToolbar.__init__(self, canvas_, parent_)


# =============================================================================
# EXECUTE PROGRAM
# =============================================================================
if __name__ == "__main__":
    app = QApplication(argv)
    ex = RunProgram()
    exit(app.exec_())

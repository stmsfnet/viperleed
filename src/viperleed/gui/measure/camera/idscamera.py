import ids_peak.ids_peak as ids_peak
import ids_peak.ids_peak_ipl_extension as ids_ipl_extension
import ids_peak_ipl.ids_peak_ipl as ids_peak_ipl
import ids_peak_ipl
import ctypes

from PIL import Image
import numpy as np
import inspect
from PyQt5 import QtCore as qtc

from viperleed.gui.measure.camera.abc import CameraABC
from viperleed.gui.measure.classes.abc import SettingsInfo
from viperleed.gui.measure import hardwarebase as base
from viperleed.gui.measure.classes.abc import QObjectSettingsErrors
from viperleed.gui.measure.dialogs.settingsdialog import SettingsHandler
from viperleed.gui.measure.dialogs.settingsdialog import SettingsTag
from viperleed.gui.measure.widgets.mappedcombobox import MappedComboBox
from viperleed.gui.measure.widgets.spinboxes import CoercingSpinBox


class LiveWorker(qtc.QObject):
    """Worker thread for live mode."""
    frame_ready = qtc.pyqtSignal(np.ndarray)

    def __init__(self, camera, datastream):
        super().__init__()
        self.camera = camera
        self.datastream = datastream
        self._running = False

    @qtc.pyqtSlot()
    def run(self):
        """Runs the while loop for camera buffers."""
        self._running = True
        
        while self._running:
            try:
                buffer = self.datastream.WaitForFinishedBuffer(1500)
                if buffer.HasImage():
                    image_np = self.camera._process_ids_mono12_buffer(buffer) 
                    if image_np is not None:
                        self.frame_ready.emit(image_np)    
            finally:
                self.datastream.QueueBuffer(buffer)

    def stop(self):
        """Stops the while loop."""
        self._running = False

class IDS(CameraABC):
    """Concrete subclass of CameraABC handling IDS_peak Cameras."""

    _mandatory_settings = (
        # pylint: disable=protected-access
        # Needed for extending
        *CameraABC._mandatory_settings,
        ('camera_settings', 'black_level'),
        )  
    def __init__(self, *args, settings=None, parent=None, **kwargs):
        """Initialize instance."""
        self.hardware_supported_features.extend(['roi', 'black_level'])
        #initialize the ids_peak library
        ids_peak.Library.Initialize()            
    
        self.device = None
        self.datastream = None
        self.remote_node_map = None
        self.has_zero_minimum = False
        self._supports_trigger_burst = False
        self.__black_level = -1
        
        self._live_thread = None
        self._live_worker = None
        self._live_thread = qtc.QThread()     
        
        #self.device_manager = ids_peak.DeviceManager.Instance()
        super().__init__(ids_peak,*args,settings=settings, parent=parent, **kwargs)

        
    @property
    def exceptions(self):
        """Return a tuple of camera exceptions.

        Returns
        -------
        exceptions : tuple
            Each element is an Exception subclass of exceptions
            that the camera may raise in case internal driver
            errors occur.
        """
        return tuple( cls for _, cls in inspect.getmembers(ids_peak, inspect.isclass) if issubclass(cls, Exception) )

    @property
    def extra_delay(self):
        """Return the interval spent not measuring when triggered (msec).
        
        Returns
        -------
        extra_delay : float
            Extra time in milliseconds required by the camera
            to complete a triggering cycle.
        """
        return 30

    @property
    def image_info(self):
        """Return information about the last image.

        Returns
        -------
        width, height : int
            Width and height of the image in pixels
        n_bytes : int
            Number of bytes per pixel and per color
        n_colors : int
            Number of color channels
        """
        #If you change the image size, you must stop image acquisition and recreate the buffers, see Starting and stopping image acquisition and Preparing image acquisition: create buffer.
        #at https://www.1stvision.com/cameras/IDS/IDS-manuals/en/height.html 
        if self.remote_node_map is None:
            raise RuntimeError("remote_node_map is None")
            
        try:
            width = self.remote_node_map.FindNode("Width").Value()
            height = self.remote_node_map.FindNode("Height").Value()
            
            pixel_format = self.remote_node_map.FindNode("PixelFormat").CurrentEntry().SymbolicValue() 
            if "16" in pixel_format:
                n_bytes = 2
            elif "12p" in pixel_format or "10p" in pixel_format:
                n_bytes = 2  
            elif "12" in pixel_format or "10" in pixel_format:
                n_bytes = 2 
            else:
                n_bytes = 1

            #only monochromatic ids cameras are used
            n_colors = 1
            return width, height, n_bytes, n_colors
        except Exception as e:
            print("EXCEPTION: image_info()" + str(e))
            return 1936,1216,2,1

    @property
    def intensity_limits(self):
        """Return the minimum and maximum value for a pixel.

        Returns
        -------
        pixel_min : int
            Minimum intensity for a pixel
        pixel_max : int
            Maximum intensity for a pixel
        """
        #IDS Cameras can generate a test image according to https://www.1stvision.com/cameras/IDS/IDS-manuals/en/test-pattern.html
        #Black: The sensor generates a test image with the darkest possible image.
        #White: The sensor generates a test image with the brightest possible image.
        if self.remote_node_map is None:
            return 0, 65520
        else:
            pixel_format = self.remote_node_map.FindNode("PixelFormat").CurrentEntry().SymbolicValue()

            #this if segment is only for monochromatic ids cameras and could be densed down
            # if this way of calculating the pixel_min and pixel_max can't be checked for Mono12p and Mono10p ()
            if "12" in pixel_format:  #Mono12
                n_bytes = 2  
                dyn_range = 12
            elif  "10" in pixel_format: #Mono10
                n_bytes = 2
                dyn_range = 10 
            else:                       #Mono8
                n_bytes = 1
                dyn_range = 8  

            max_bit = n_bytes * 8

            if max_bit >= dyn_range:
                self.has_zero_minimum = True
            else:
                self.has_zero_minimum = False

            if self.has_zero_minimum:
                min_bit = 0
                delta = 1
            else:
                min_bit = max_bit - dyn_range
                delta = 0

            pixel_min = 2**min_bit-delta
            pixel_max = 2**max_bit - 2**(max_bit-dyn_range) +2**min_bit - 1

            return pixel_min, pixel_max

    @property
    def is_running(self):
        """Return whether the camera is currently running.
        
        Returns
        -----
        running: bool
            True if the camera firmware is currently acquiring or
            processing images, False otherwise.
        """
        if self.datastream is None:
            return False
        else:
            return True
        #SensorState according to: https://www.1stvision.com/cameras/IDS/IDS-manuals/en/sensor-state.html  -> only available uEye+: GV and U3 cameras     
        #sensor_state = self.remote_node_map.FindNode("SensorState").CurrentEntry().SymbolicValue()
               
    @property
    def black_level(self):
        """Return the black-level setting of the camera.

        The black level is a measure of a minimum photon intensity
        at pixels. Pixels illuminated with less than this intensity
        will appear in images as having self.intensity_limits[0]
        intensity. Therefore, black_level determines the lower limit
        at which image-intensity histograms are 'cut'.
        """
        try:
            black_level = self.settings.getint('camera_settings',
                                               'black_level', fallback=-2)
        except (TypeError, ValueError):
            black_level = -2

        if black_level == self.__black_level:
            return black_level

        if black_level <= -2:
            # Was not present. Let's read it from the camera
            # and store it in the settings.
            black_level = self.get_black_level()
            self.settings.set('camera_settings', 'black_level',
                              str(black_level))
            self.settings.update_file()

        _min, _max = self.get_black_level_limits()
        if black_level < _min or black_level > _max:
            self.emit_error(
                QObjectSettingsErrors.INVALID_SETTINGS,
                'camera_settings/black_level',
                f"{black_level} [out of range ({_min}, {_max})]",
                )
            return -2

        self.__black_level = black_level
        return black_level



    @property
    def supports_trigger_burst(self):
        """Return whether the camera allows triggering multiple frames.
        
        Returns
        -----
        supported : bool
            True if the camera internally supports triggering multiple
            frames, i.e., only one 'trigger_now()' call is necessary to
            deliver all the frames needed.
        """
        return self._supports_trigger_burst


    def check_loaded_settings(self):
        """IDS Cameras exposure and gain values are discrete. 
        This assures that the values in self.settings match with the real values in the camera.
        
        Returns
        --------
        setting_match : bool
            True if the settings in the camera and in self.settings
            are the same.

        """
        real_exposure = self.remote_node_map.FindNode("ExposureTime").Value() / 1000
        expected_exposure = self.settings.getfloat('measurement_settings','exposure')

        real_gain = self.remote_node_map.FindNode("Gain").Value()
        expected_gain = self.settings.getfloat('measurement_settings','gain')

        if expected_exposure != real_exposure:
            self.settings.set('measurement_settings', 'exposure', str(real_exposure))
        if expected_gain != real_gain:
            self.settings.set('measurement_settings', 'gain', str(real_gain))        
        
        self.settings.update_file()

        return super().check_loaded_settings()


    def close(self):
        """Closes the camera. 'For IDS cameras the reference to the object must be destroy, 
        by either going out-of-scope or by explicitly overwriting the variable.' """
        

        if self.device is not None or self.datastream is not None or self.remote_node_map is not None:
            self.stop()
            self.datastream = None
            self.remote_node_map = None
            self.device = None

        ids_peak.Library.Close()

    @classmethod
    def is_matching_default_settings(cls, obj_info, config, match_exactly):
        """Determine if the default `config` file is for this camera.

        Parameters
        ----------
        obj_info : SettingsInfo or None
            The information that should be used to check `config`.
        config : ConfigParser
            The settings to check.
        match_exactly : bool
            Whether obj_info should be matched exactly.

        Returns
        -------
        sorting_info : tuple
            A tuple that can be used to sort the detected settings.
            Larger values in the tuple indicate a higher degree of
            conformity. The order of the items in the tuple is the
            order of their significance. This return value is used
            to determine the best-matching settings files when
            multiple files are found. An empty tuple signifies that
            `config` does not match the requirements.
        """
        # As imagingsource.py says:
        # Note that we can just return matching here, as we already
        # know that the class matches. The reason for this is that the
        # relevant camera attributes taken from the settings files do
        # not change between the various cameras handled by this class.
        return (1,)

    @classmethod
    def is_matching_user_settings(cls, obj_info, config, match_exactly):
        """Determine if the default `config` file is for this camera.

        Parameters
        ----------
        obj_info : SettingsInfo or None
            The information that should be used to check `config`.
        config : ConfigParser
            The settings to check.
        match_exactly : bool
            Whether obj_info should be matched exactly.

        Returns
        -------
        sorting_info : tuple
            A tuple that can be used to sort the detected settings.
            Larger values in the tuple indicate a higher degree of
            conformity. The order of the items in the tuple is the
            order of their significance. This return value is used
            to determine the best-matching settings files when
            multiple files are found. An empty tuple signifies that
            `config` does not match the requirements.
        """
        super().is_matching_user_settings(obj_info, config, match_exactly)
        camera_name = config.get('camera_settings', 'device_name',
                                 fallback=None)
        if match_exactly:
            return (1,) if camera_name == obj_info.unique_name else ()
        if camera_name is None:
            return ()
        camera_name_re = base.device_name_re(camera_name)
        return (1,) if camera_name_re.match(obj_info.unique_name) else ()


    @classmethod
    def is_settings_for_this_class(cls, config):                               
        """Determine if a `config` file is for this camera.

        Parameters
        ----------
        config : ConfigParser
            The settings to check.

        Returns
        -------
        is_suitable : bool
            True if the settings file is for this camera.
        """
        camera_class = config.get('camera_settings', 'class_name',
                                  fallback=None)
        return cls.__name__ == camera_class


    def get_settings_handler(self):
        """Return a SettingsHandler object for displaying settings.

        Adds:
        - 'camera_settings'/'black_level' (advanced)

        Returns
        -------
        handler : SettingsHandler
            The handler used in a SettingsDialog to display the
            settings of this controller to users.
        """
        base_handler = super().get_settings_handler()
        handler = SettingsHandler(self.settings, show_path_to_config=True)
        handler.add_from_handler(base_handler)

        # pylint: disable=redefined-variable-type
        # Triggered for _widget. While this is true, it is clear what
        # _widget is used for in each portion of filling the handler

        if not self.connected:
            return handler

        # Black level
        _widget = CoercingSpinBox(soft_range=self.get_black_level_limits())
        _widget.setMinimum(0)
        _widget.setAccelerated(True)
        _tip = (
            "<nobr>Dark Level, Black Level, or Brightness is a measure of"
            "</nobr> minimum photon intensity at pixels. Pixels illuminated "
            "with less than this intensity will appear in images as "
            f"having minimum intensity (= {self.intensity_limits[0]}). "
            "Therefore, it determines the lower limit at which image-"
            "intensity histograms are 'cut'. The dark level is <b>optimized "
            "automatically</b> before bad pixels are identified with "
            "<b>Tools->Find bad pixels...</b>"
            )
        handler.add_option('camera_settings', 'black_level',
                           handler_widget=_widget, tooltip=_tip,
                           tags=SettingsTag.ADVANCED,
                           display_name="Dark Level")
        return handler

    def list_devices(self):
        """Return a list of available devices.
        
        Returns
        ------
        devices : list of SettingsInfo
            Information for each of the detected Imaging Source cameras.
            For each item, only .unique_name and .has_hardware_interface
            are set, i.e., there is no .more information.
        """
        ids_peak.Library.Initialize()
        self.device_manager = ids_peak.DeviceManager.Instance()
        self.device_manager.Update()
        present = True
        return  [SettingsInfo(name.DisplayName(),   present) for name in self.device_manager.Devices()]
    
    def open(self): 
        """Open the camera device.

        After execution of this method the camera is ready
        to deliver frames.        

        Returns
        -------
        successful : bool
            True if the device was opened successfully.                     
        """

        ids_peak.Library.Initialize()
        self.device_manager = ids_peak.DeviceManager.Instance()
        self.device_manager.Update()

        if self.device is None:
            try:
                for i,name in enumerate(self.device_manager.Devices()):
                    if name.DisplayName() == self.name:
                        self.device = self.device_manager.Devices()[i].OpenDevice(ids_peak.DeviceAccessType_Control)
            except Exception as e:
                print("EXCEPTION: open()" + str(e))          
            finally:
                if self.device is None:
                    return False
                self.remote_node_map = self.device.RemoteDevice().NodeMaps()[0]
                self.datastream = self.device.DataStreams()[0].OpenDataStream()

                if not self._supports_trigger_burst:                               
                    try:
                        self.remote_node_map.TryFindNode("AcquisitionMode").SetCurrentEntry("MultiFrame")

                        self._supports_trigger_burst = True
                    except Exception as e:
                        print("EXCEPTION: " + str(e))
                        self._supports_trigger_burst = False
                
                self.set_roi(no_roi=True)
                #set the pixelformat for used ids cameras to  monochrome 12 bit, default is monochrome 8 bit
                self.remote_node_map.FindNode("PixelFormat").SetCurrentEntry("Mono12")
                self.remote_node_map.FindNode("AcquisitionMode").SetCurrentEntry("SingleFrame")
                self.set_roi()
                return True
        else:
            return True

    @qtc.pyqtSlot()
    def get_black_level(self):
        """Return the black level currently set in the camera."""
        return self.remote_node_map.FindNode("BlackLevel").Value()

    @qtc.pyqtSlot()
    def set_black_level(self):
        """Set the black level in the camera from settings."""
        _level = self.black_level
        if _level <0:
            return
        self.remote_node_map.FindNode("BlackLevel").SetValue(_level)


    def get_black_level_limits(self):
        """Return minimum and maximum values for the black level."""
        _black_level_node = self.remote_node_map.FindNode("BlackLevel")
        return _black_level_node.Minimum(), _black_level_node.Maximum()


    def get_binning(self): #TODO: Reactivate binning function and implement set_binning: File "/home/aop2diplom/viperleed-git/src/viperleed/gui/measure/camera/abc.py", line 1073, in set_binning raise NotImplementedError(NotImplementedError: IDS natively supports binning, but self.set_binning() was not overridden.

        """IDS cameras support binning, even in vertical AND horizontal direction. For IDS cameras the default binning factor is 1.
        
        Returns
        ----
        binning_factor: int
                Linear number of pixels used for binning.
                IDS Cameras have 2 binning factors ( vertical, horizontal),
                binning_factor = max(binning_vertical, binning_horizontal) 
                Tested IDS Cameras only support a binning_factor of max. 2
        """ 
        return None

    def get_exposure(self):
        """Return the exposure time in milliseconds set in the camera."""
        #https://www.1stvision.com/cameras/IDS/IDS-manuals/en/exposure-time.html
        return self.remote_node_map.FindNode("ExposureTime").Value() / 1000

    def set_exposure(self):
        """Set the exposure time."""
        #https://www.1stvision.com/cameras/IDS/IDS-manuals/en/exposure-time.html
        if self.remote_node_map is None:
            raise RuntimeError("set_exposure, remotenodemap none") 
        else:
            new_frame_rate = 1/ ( (self.exposure*1.01) / 1000)
            max_frame_rate = self.remote_node_map.FindNode("AcquisitionFrameRate").Maximum()
            min_frame_rate = self.remote_node_map.FindNode("AcquisitionFrameRate").Minimum()

            if min_frame_rate > new_frame_rate:
                self.remote_node_map.FindNode("AcquisitionFrameRate").SetValue(min_frame_rate)
            elif new_frame_rate > max_frame_rate:
                self.remote_node_map.FindNode("AcquisitionFrameRate").SetValue(max_frame_rate*0.999)
            else:
                self.remote_node_map.FindNode("AcquisitionFrameRate").SetValue(new_frame_rate)
                
            self.remote_node_map.FindNode("AcquisitionFrameRate").Value()
            self.remote_node_map.FindNode("ExposureTime").SetValue(self.exposure * 1000)

    def get_exposure_limits(self): 
        """Return the minimum and maximum exposure time supported.
        
        Returns
        ------
        min_exposure, max_exposure : float
            Shortest and longest exposure times in milliseconds
        """
        if self.remote_node_map is None:
            return 0 , np.inf
        else:
            self._starting_frame_rate = self.remote_node_map.FindNode("AcquisitionFrameRate").Value()
            self.remote_node_map.FindNode("AcquisitionFrameRate").SetValue(1)
            node_exposure_time = self.remote_node_map.FindNode("ExposureTime")
            min_exposure_time = node_exposure_time.Minimum() / 1000
            max_exposure_time = node_exposure_time.Maximum() / 1000
            self.remote_node_map.FindNode("AcquisitionFrameRate").SetValue(self._starting_frame_rate)
            return min_exposure_time, max_exposure_time

    def get_frame_rate(self):
        """Return the number of frames delivered per second
        
        Returns
        -------
        frame_rate : float
            Number of frames delivered per second.                
        """
        if self.remote_node_map is None:
            return 25.0
        else:
            return self.remote_node_map.FindNode("AcquisitionFrameRate").Value() 

    def get_gain(self):
        """Get the gain in dB from camera.

        Returns
        -------
        gain : float
            Gain in decibel.

        """
        if self.remote_node_map is None:
            return 1.00
        else:
            return self.remote_node_map.FindNode("Gain").Value()
    
    def set_gain(self):
        """Set the gain of the camera in dB."""

        #raise RuntimeError(f"{self.remote_node_map.FindNode("Gain").Value()}, {self.gain}")
        if self.remote_node_map is not None:
            self.remote_node_map.FindNode("Gain").SetValue(self.gain)

    def get_gain_limits(self):
        """Returns the minimum and maximum gains supported.
        
        Returns
        ------
        min_gain, max_gain : float

        """
        if self.remote_node_map is None:
            return 1,24.0
        else:
            gain_min = self.remote_node_map.FindNode("Gain").Minimum()
            gain_max = self.remote_node_map.FindNode("Gain").Maximum()
            return gain_min , gain_max
    

    def get_mode(self):
        """Return the mode set in the camera.

        Returns:
        -------
        mode : {'live', 'triggered'}
            The mode the camera is operating in.
            Continuous (= live): Images are captured until stopped with the AcquisitionStop command
            SingleFrame (= triggered): One image is captured only when asked by self.trigger_now()
            'triggered' is asynchronous: the camera returns a frame
            only when asked by self.trigger_now().

        Another possible AcquisitionMode IDS camera can use is MultiFrame (tested cameras can't support this mode)
        MultiFrame: Number of images specified by AcquisitionFrameCount is captured. only supported by uEye+ cameras (GV and U3 models)
        """
        #https://www.1stvision.com/cameras/IDS/IDS-manuals/en/acquisition-mode.html
        return 'triggered' if self.remote_node_map.FindNode("AcquisitionMode").CurrentEntry().SymbolicValue() != "Continuous" else "live"

    def set_mode(self):
        """Set the camera mode"""
        if self.mode == "triggered" and self.device is not None:
            self.remote_node_map.FindNode("AcquisitionMode").SetCurrentEntry("SingleFrame")
            
        else:
            self.remote_node_map.FindNode("TriggerMode").SetCurrentEntry("Off")

            self.remote_node_map.FindNode("AcquisitionMode").SetCurrentEntry("Continuous") 

    def get_n_frames(self):
        """Return zero as the camera does not support frame averaging."""
        return 0
    
    def get_roi(self):
        """Return the region of interest set in the camera.

        Returns
        -------
        tuple
            The settings of the region of interest. If the camera
            supports hardware ROI, this method returns:
            roi_x, roi_y : int
                Coordinates of the top-left pixel. Zero is the
                topmost/leftmost pixel.
            roi_width, roi_height : int
                Width and height of the region of interest in pixels
        """
        if self.remote_node_map is None:
            return (0,0,1936,1216)
        else:
            #https://www.1stvision.com/cameras/IDS/IDS-manuals/en/program-set-roi.html
            roi_x = self.remote_node_map.FindNode("OffsetX").Value()
            roi_y = self.remote_node_map.FindNode("OffsetY").Value()
            roi_width = self.remote_node_map.FindNode("Width").Value()
            roi_height = self.remote_node_map.FindNode("Height").Value()

            return roi_x, roi_y, roi_width, roi_height

    def set_roi(self,no_roi =False):
        """Set up region of interest in the camera
        
        Parameters
        -----------
        no_roi : bool, optional
            If True, set the ROI to the full size of the sensor rather
            than using the value from the settings. Default is True.
        """
        if self.remote_node_map is None:
            raise RuntimeError("remote_node_map is none")
        
        if no_roi:      
            roi = (0, 0, self.remote_node_map.FindNode("Width").Maximum(), self.remote_node_map.FindNode("Height").Maximum())
        else:
            roi = self.roi
        roi_x, roi_y, roi_width, roi_height = roi
        
        self.remote_node_map.FindNode("Width").SetValue(roi_width)
        self.remote_node_map.FindNode("Height").SetValue(roi_height)
        self.remote_node_map.FindNode("OffsetX").SetValue(roi_x)
        self.remote_node_map.FindNode("OffsetY").SetValue(roi_y)

    def get_roi_size_limits(self):
        """Return minimum, maximum and granularity of the ROI.

        Returns
        -------
        roi_min : tuple
            Two elements, both integers, corresponding to the
            minimum width and minimum height
        roi_max : tuple
            Two elements, both integers, corresponding to the
            maximum width and maximum height
        roi_increments : tuple
            Two elements, both integers, corresponding to the
            minimum allowed increments for width and height of
            the region of interest
        roi_offset_increments : tuple
            Two elements, both integers, corresponding to the
            minimum allowed increments for the horizontal and
            vertical position of the roi.
        """
        if self.remote_node_map is None:
            return (0,0), (1936,1216), (2,2),(2,2)
        else:
            #https://www.1stvision.com/cameras/IDS/IDS-manuals/en/program-set-roi.html
            roi_min = (self.remote_node_map.FindNode("Width").Minimum(), self.remote_node_map.FindNode("Height").Minimum())
            roi_max = (self.remote_node_map.FindNode("Width").Maximum(), self.remote_node_map.FindNode("Height").Maximum())

            roi_increments = (self.remote_node_map.FindNode("Width").Increment(), self.remote_node_map.FindNode("Height").Increment())
            roi_offset_increments = (self.remote_node_map.FindNode("OffsetX").Increment(), self.remote_node_map.FindNode("OffsetY").Increment())

            return roi_min, roi_max, roi_increments, roi_offset_increments


    def reset(self):
        """Reset the camera to FACTORY default settings."""
        self.remote_node_map.FindNode("ResetToFactoryDefaults").Execute()
        self.remote_node_map.FindNode("ResetToFactoryDefaults").WaitUntilDone()

    def set_callback(self, on_frame_ready): #TODO: 
        """Pass a frame-ready callback to the camera driver.

        If the camera does not support having a callback function,
        a similar behavior can be obtained using an appropriate
        pyqtSignal, emitted as soon as a frame has been acquired.

        Parameters
        ----------  
        on_frame_ready : callable
            The function that will be called by the camera each time
            a new frame arrives. The callback should only care of
            converting the data from the camera into a numpy.array
            of appropriate shape and data type, then emitting a
            frame_ready signal carrying the array. It must be able
            to take a reference to self as part of its arguments:
            It may do so either taking self directly or taking
            self.process_info (.camera is a reference to self).
            It can then access methods of the driver via self.driver.

        Returns
        -------
        None
        """
        return

    @qtc.pyqtSlot()
    @qtc.pyqtSlot(object)
    def start(self, *_):
        """Start the camera in self.mode
        Returns
        -------
        None.
        """        
        super().start()
        print(f"self.open is {self.open()}")
        if self.mode == "triggered":            
            self.revoke_buffer()
            self.alloc_buffer()            
            self.n_frames_done = 0  
            self.init_software_trigger()
            self.datastream.StartAcquisition()

        elif self.mode == "live":
            self.revoke_buffer()
            self.alloc_buffer()

            self.remote_node_map.FindNode("TriggerMode").SetCurrentEntry("Off")
            self.remote_node_map.FindNode("AcquisitionMode").SetCurrentEntry("Continuous")
            self.remote_node_map.FindNode("TLParamsLocked").SetValue(1)

            self.datastream.StartAcquisition()
            self.remote_node_map.FindNode("AcquisitionStart").Execute()

            self._live_thread = qtc.QThread()
            self._live_worker = LiveWorker(self,self.datastream)
            self._live_worker.moveToThread(self._live_thread)

            self._live_thread.started.connect(self._live_worker.run)
            self._live_worker.frame_ready.connect(self.frame_ready.emit)
            self._live_thread.start()                
        
        self.started.emit()

    @qtc.pyqtSlot()
    def stop(self):
        """Stop the camera."""
        if not super().stop():
            # No need to stop, or cannot stop yet
            return False

        try:
            if self._live_worker is not None:
                self._live_worker.stop()
            if self._live_thread is not None:
                self._live_thread.quit()
                self._live_thread.wait()
                self._live_thread = None
                self._live_worker = None
        except Exception as e:
            print("EXCEPTION: stop thread - " + str(e))
        
        #stop acquisition on camera
        if self.remote_node_map is None:
            return False
        
        self.remote_node_map.FindNode("AcquisitionStop").Execute()

        if self.datastream.IsGrabbing():
            self.datastream.StopAcquisition()

        #revoke all buffers ( Discard all buffers from the acquisition engine, because they remain in the announced buffer pool.)
        self.revoke_buffer()

        self.stopped.emit()
        return True

    @qtc.pyqtSlot()
    def trigger_now(self):

        """Start acquiring one (or more) frames now.

        Returns
        -------
        successfully_triggered : bool
            True if the camera was successfully triggered.

        Emits
        -----
        error_occurred(CameraErrors.UNSUPPORTED_OPERATION)
        """
        if not super().trigger_now():
            return False
       
        #Lock writable nodes, which could influence the payload size during acquisition.
        self.remote_node_map.FindNode("TLParamsLocked").SetValue(1)
        self.remote_node_map.FindNode("AcquisitionStart").Execute()
        #Check if the command has finished before you continue (optional)
        # self.remote_node_map.FindNode("AcquisitionStart").WaitUntilDone()

        #image trigger
        self.remote_node_map.FindNode("TriggerSoftware").Execute()
        self.remote_node_map.FindNode("TriggerSoftware").WaitUntilDone()

        buffer = self.datastream.WaitForFinishedBuffer(ids_peak.Timeout.INFINITE_TIMEOUT)

        extracted_image = self._process_ids_mono12_buffer(buffer) 
        self.frame_ready.emit(extracted_image.copy())
        
        self.datastream.QueueBuffer(buffer)

        self.remote_node_map.FindNode("AcquisitionStop").Execute()
        self.remote_node_map.FindNode("AcquisitionStop").WaitUntilDone()

        self.remote_node_map.FindNode("TLParamsLocked").SetValue(0)
        return True

    def _process_ids_mono12_buffer(self,buffer):
        """Converts buffer(Mono12) to a Mono16 image.

        Parameter
        --------
        buffer: The buffer containing the acquired frame
        --------
        Emits
        image_2d: Mono16
        """
        width = buffer.Width()
        height = buffer.Height()
        size = buffer.Size()
        ptr_address = int(buffer.BasePtr())
        buffer_bytes = ctypes.string_at(ptr_address,size)

        raw_data = np.frombuffer(buffer_bytes,dtype='<u2')
        image_2d = raw_data.reshape((height, width))

        return image_2d <<4

    def init_software_trigger(self):
        """Initialize the software Trigger.
        Sets the TriggerSelector to ExposureStart, the TriggerMode to On and the TriggerSource to Software.
        """
        
        self.remote_node_map.FindNode("TriggerSelector").SetCurrentEntry("ExposureStart")
        self.remote_node_map.FindNode("TriggerMode").SetCurrentEntry("On")
        self.remote_node_map.FindNode("TriggerSource").SetCurrentEntry("Software")


    def alloc_buffer(self):
        """Allocates the buffer, needed for start()"""
        # if self.remote_node_map is None:
        #     raise RuntimeError("This RunTimeError is one time only, after restart of ViPErLEED this shouldn't be a problem!")
        
        #Buffer size
        payload_size = self.remote_node_map.FindNode("PayloadSize").Value()

        #Number of minimum required buffers
        if self.datastream.NumBuffersAnnouncedMinRequired() >=3:
            self.num_buffers_min_required = self.datastream.NumBuffersAnnouncedMinRequired()
        else:
            self.num_buffers_min_required = 3

        #Allocate buffers
        for _ in range(self.num_buffers_min_required):
            buffer = self.datastream.AllocAndAnnounceBuffer(payload_size)
            self.datastream.QueueBuffer(buffer)
        
    def revoke_buffer(self):
        """Revokes the buffer, needed for stop()"""
        
        # if self.datastream is None:
            # raise RuntimeError("This RunTimeError is one time only, after restart of ViPErLEED this shouldn't be a problem!")

        #stop and flush the datastream
        if self.datastream.IsGrabbing():
            self.datastream.StopAcquisition(ids_peak.AcquisitionStopMode_Kill)
            
        # Remove buffers from any associated queue
        self.datastream.Flush(ids_peak.DataStreamFlushMode_DiscardAll)

        #Clear all old buffers
        for buffer in self.datastream.AnnouncedBuffers():
            self.datastream.RevokeBuffer(buffer)

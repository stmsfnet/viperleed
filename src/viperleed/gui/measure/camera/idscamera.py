import ids_peak.ids_peak as ids_peak
import ids_peak.ids_peak_ipl_extension as ids_ipl_extension
import ids_peak_ipl.ids_peak_ipl as ids_ipl

from PIL import Image
import numpy as np
import inspect
from PyQt5 import QtCore as qtc

from viperleed.gui.measure.camera.abc import CameraABC
from viperleed.gui.measure.classes.abc import SettingsInfo
from viperleed.gui.measure import hardwarebase as base

class LiveWorker(qtc.QObject):
    """Worker thread for live mode."""
    frame_ready = qtc.pyqtSignal(np.ndarray)

    def __init__(self, device, datastream):
        super().__init__()
        self.device = device
        self.datastream = datastream
        self._running = False

    @qtc.pyqtSlot()
    def run(self):
        """Runs the while loop for camera buffers."""
        self._running = True
        
        while self._running:
            try:
                buffer = self.datastream.WaitForFinishedBuffer(500)
                if buffer.HasImage():
                    image_np = self.device._buff_to_numpy(buffer)
                    if image_np is not None:
                        self.frame_ready.emit(image_np)    
            except:
                continue
            finally:
                self.datastream.QueueBuffer(buffer)

    def stop(self):
        """Stops the while loop."""
        self._running = False

class IDS(CameraABC):
    """Concrete subclass of CameraABC handling IDS_peak Cameras."""

    #_mandatory_settings = (*CameraABC._mandatory_settings,)
    
    def __init__(self, *args, settings=None, parent=None, **kwargs):
        """Initialize instance."""
        #self.hardware_supported_features.extend(['roi', 'black_level', 'color_format']) #TODO: IDS camera hardware support roi, black_level and color_format (get_[name] and set_[name] methods need to be implemented)
        self.hardware_supported_features.extend(['roi'])
        #initialize the ids_peak library
        ids_peak.Library.Initialize()            

        self.device = None
        self.datastream = None
        self.remote_node_map = None
        self.has_zero_minimum = False
        
        
        self.__has_callback = None
        self._live_thread = None
        self._live_worker = None
        self._live_thread = qtc.QThread()     

        #initialize device_manager used in list_devices() and open()
        
        self.device_manager = ids_peak.DeviceManager.Instance()
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
        #https://www.1stvision.com/cameras/IDS/IDS-manuals/en/operate-software-trigger.html 
        frame_rate = self.get_frame_rate()
        return (1000 / frame_rate) if frame_rate > 0 else 0
        #return 1 / self.get_frame_rate() *10**6

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
        # width = 1936
        # height = 1216
        if self.remote_node_map is None:
            width = 1936
            height = 1216
            
        try:
            width = self.remote_node_map.FindNode("Width").Value()
            height = self.remote_node_map.FindNode("Height").Value()

            pixel_format = self._pixel_format

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
        except Exception:
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
        if self.device is None or self.datastream is None:
            return False
        
        #SensorState according to: https://www.1stvision.com/cameras/IDS/IDS-manuals/en/sensor-state.html  -> only available uEye+: GV and U3 cameras     
        #sensor_state = self.remote_node_map.FindNode("SensorState").CurrentEntry().SymbolicValue()
        
        try:
            return self.datastream.NodeMaps()[0].FindNode("StreamIsGrabbing").Value() 
        except Exception:
            return False



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
        
        try:
            self.remote_node_map.TryFindNode("AcquisitionMode").SetCurrentEntry("MultiFrame")
            return True
        except Exception:
            return False

    def close(self):
        """Closes the camera. 'For IDS cameras the reference to the object must be destroy, 
        by either going out-of-scope or by explicitly overwriting the variable.' """
        if self.device is not None:
            
            self.stop()
            self.datastream = None
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

        #self.name to check if this works
        #self.name = "IDS UI326xCP-M (IDS/UI326xCP-M/4103712875-0)"

        try:
            # self.device_manager.Update()
            ids_peak.Library.Initialize()
            self.device_manager = ids_peak.DeviceManager.Instance()
            self.device_manager.Update()
            #count is needed to open ANY ids camera and not just the first openable camera
            count = 0 
            for name in self.device_manager.Devices():
                if name.DisplayName() == self.name:
                    
                    self.device = self.device_manager.Devices()[count].OpenDevice(ids_peak.DeviceAccessType_Control)
                    self.set_roi(no_roi=True)

                    self.remote_node_map = self.device.RemoteDevice().NodeMaps()[0]
                    self.datastream = self.device.DataStreams()[0].OpenDataStream()

                    #set the pixelformat for used ids cameras to  monochrome 12 bit, default is monochrome 8 bit
                    self.remote_node_map.FindNode("PixelFormat").SetCurrentEntry("Mono12")
                    self._pixel_format = self.remote_node_map.FindNode("PixelFormat").CurrentEntry().SymbolicValue() 
                    self.set_roi()

                    return True
                count+=1
            return False
                
        except Exception: 
            return False

    def get_binning(self): #TODO: Reactivate binning function and implement set_binning: File "/home/aop2diplom/viperleed-git/src/viperleed/gui/measure/camera/abc.py", line 1073, in set_binning raise NotImplementedError(NotImplementedError: IDS natively supports binning, but self.set_binning() was not overridden.

        """IDS cameras support binning, even in vertical AND horizontal direction.
        
        Returns
        ----
        binning_factor: int
                Linear number of pixels used for binning.
                IDS Cameras have 2 binning factors ( vertical, horizontal),
                binning_factor = max(binning_vertical, binning_horizontal) 
                Tested IDS Cameras only support a binning_factor of max. 2
        """ 
        if self.remote_node_map is None:
            return None
        # binning_vertical = self.remote_node_map.FindNode("BinningVertical").Value()
        # binning_horizontal = self.remote_node_map.FindNode("BinningHorizontal").Value()
        
        # if binning_vertical == binning_horizontal:
        #     return binning_vertical
        # else:
        #     self.remote_node_map.FindNode("BinningVertical").SetValue(binning_horizontal)
        #     return binning_horizontal

            

    def get_exposure(self):
        """Return the exposure time in milliseconds set in the camera.""" #ids cameras use microseconds
        #https://www.1stvision.com/cameras/IDS/IDS-manuals/en/exposure-time.html
        return self.remote_node_map.FindNode("ExposureTime").Value() / 1000

    def set_exposure(self):
        """Set the exposure time.""" #ids cameras use microseconds
        #https://www.1stvision.com/cameras/IDS/IDS-manuals/en/exposure-time.html
        self.remote_node_map.FindNode("ExposureTime").SetValue(self.exposure * 1000)

    def get_exposure_limits(self): 
        """Return the minimum and maximum exposure time supported.
        
        Returns
        ------
        min_exposure, max_exposure : float
            Shortest and longest exposure times in milliseconds
        """
        #ids cameras use microseconds 
        exposure_time = self.remote_node_map.FindNode("ExposureTime")       
        return exposure_time.Minimum() / 1000, exposure_time.Maximum() / 1000

    def get_frame_rate(self):
        """Return the number of frames delivered per second
        
        Returns
        -------
        frame_rate : float
            Number of frames delivered per second.                
        """
        return self.remote_node_map.FindNode("AcquisitionFrameRate").Value() 

    def get_gain(self):
        """Get the gain in dB from camera.

        Returns
        -------
        gain : float
            Gain in decibel.

        """
        return self.remote_node_map.FindNode("Gain").Value()
    
    def set_gain(self):
        """Set the gain of the camera in dB."""
        self.remote_node_map.FindNode("Gain").SetValue(self.gain)

    def get_gain_limits(self):
        """Returns the minimum and maximum gains supported.
        
        Returns
        ------
        min_gain, max_gain : float

        """
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
        if self.mode == "triggered":
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
            return
        
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
        self.alloc_buffer()

        if self.mode == "live":
            self.remote_node_map.FindNode("TLParamsLocked").SetValue(1)
            self.datastream.StartAcquisition()
            self.remote_node_map.FindNode("AcquisitionStart").Execute()

            
            self._live_worker = LiveWorker(self.device, self.datastream)
            self._live_worker.moveToThread(self._live_thread)
            self._live_thread.started.connect(self._live_worker.run)
            self._live_worker.frame_ready.connect(self.frame_ready.emit)
            
            self._live_thread.start()

        elif self.mode == "triggered":

            self.n_frames_done = 0
            self.init_software_trigger()
            
        
        self.started.emit()

    @qtc.pyqtSlot()
    def stop(self):
        """Stop the camera."""
        if not super().stop():
            # No need to stop, or cannot stop yet
            return False
        
        try:
            #stop thread
            if self._live_worker is not None:
                self._live_worker.stop()
            if self._live_thread is not None:
                self._live_thread.quit()
                self._live_thread.wait()
                self._live_thread = None
                self._live_worker = None

            #stop acquisition on camera
            self.remote_node_map.FindNode("AcquisitionStop").Execute()

            #stop and flush the datastream
            if self.datastream.IsGrabbing():
                self.datastream.StopAcquisition(ids_peak.AcquisitionStopMode_Kill)

            #revoke all buffers ( Discard all buffers from the acquisition engine, because they remain in the announced buffer pool.)
            self.revoke_buffer()

        except Exception:
            pass

        self.stopped.emit()
        return True
    
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
        try:
            self.busy = True
            self.datastream.StartAcquisition()

            #Lock writable nodes, which could influence the payload size during acquisition.
            self.remote_node_map.FindNode("TLParamsLocked").SetValue(1)
            self.remote_node_map.FindNode("AcquisitionStart").Execute()
            #Check if the command has finished before you continue (optional)
            self.remote_node_map.FindNode("AcquisitionStart").WaitUntilDone()

            #image trigger
            self.remote_node_map.FindNode("TriggerSoftware").Execute()
            self.remote_node_map.FindNode("TriggerSoftware").WaitUntilDone()

            buffer = self.datastream.WaitForFinishedBuffer(5000) #5000ms timeout is used in ids cameras example code

            if buffer.HasImage():
                captured_image = self._buff_to_numpy(buffer)
                self.frame_ready.emit(captured_image)
        except:
            pass
        finally:
            if buffer is not None:
                try:
                    self.datastream.QueueBuffer(buffer)
                except Exception:
                    pass
            try:
                #Unlock writable nodes, which could influence the payload size during acquisition.
                self.remote_node_map.FindNode("TLParamsLocked").SetValue(0)

                self.remote_node_map.FindNode("AcquisitionStop").Execute()
                #Check if the command has finished before you continue (optional)
                self.remote_node_map.FindNode("AcquisitionStop").WaitUntilDone()

                if self.datastream.IsGrabbing():
                    self.datastream.StopAcquisition(ids_peak.AcquisitionStopMode_Kill)
            except Exception:
                return False
            self.busy = False
            return True


    def _buff_to_numpy(self, buffer): 
        """Convert buffer to numpy array and emit frame_ready signal.

        Parameter
        ------
        buffer: The buffer containing the acquired frame

        Emits image.copy()
        """
        try:
            raw_image = ids_ipl_extension.BufferToImage(buffer)
            #image = Image.fromarray(raw_image)
            return raw_image.get_numpy_2D_16().byteswap(True)
        except Exception:
            return None  


    def init_software_trigger(self):
        """Initialize the software Trigger.
        Sets the TriggerSelector to ExposureStart, the TriggerMode to On and the TriggerSource to Software.
        """
        self.remote_node_map.FindNode("TriggerSelector").SetCurrentEntry("ExposureStart")
        self.remote_node_map.FindNode("TriggerMode").SetCurrentEntry("On")
        self.remote_node_map.FindNode("TriggerSource").SetCurrentEntry("Software")

    def alloc_buffer(self):
        """Allocates the buffer, needed for start()"""
        if self.device is None:
            raise RuntimeError
        
        #Buffer size
        payload_size = self.remote_node_map.FindNode("PayloadSize").Value()

        #Number of minimum required buffers
        self.num_buffers_min_required = self.datastream.NumBuffersAnnouncedMinRequired()

        #Allocate buffers
        for _ in range(self.num_buffers_min_required):
            buffer = self.datastream.AllocAndAnnounceBuffer(payload_size)
            self.datastream.QueueBuffer(buffer)
        
    def revoke_buffer(self):
        """Revokes the buffer, needed for stop()"""
        if self.device is None:
            raise RuntimeError
        
        # Remove buffers from any associated queue
        self.datastream.Flush(ids_peak.DataStreamFlushMode_DiscardAll)

        #Clear all old buffers
        for buffer in self.datastream.AnnouncedBuffers():
            self.datastream.RevokeBuffer(buffer)

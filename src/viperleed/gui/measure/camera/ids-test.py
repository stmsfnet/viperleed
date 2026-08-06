import ids_peak.ids_peak as ids_peak
from matplotlib import pyplot as plt
import ids_peak.ids_peak_ipl_extension as ids_ipl_extension
import ids_peak_ipl.ids_peak_ipl as ids_ipl
import ids_peak_ipl
from viperleed.gui.measure.classes.abc import SettingsInfo
from PIL import Image
import numpy as np
import inspect
from viperleed.gui.measure.camera.abc import CameraABC



class Test_ids:
    def __init__(self):

        ids_peak.Library.Initialize()
        self.device_manager = ids_peak.DeviceManager.Instance()




    def list_devices(self):
        """Return a list of available devices.
        
        Returns
        ------
        devices : list of SettingsInfo
            Information for each of the detected Imaging Source cameras.
            For each item, only .unique_name and .has_hardware_interface
            are set, i.e., there is no .more information.
        """
        self.device_manager.Update()
        present = True
        return  [SettingsInfo(name.DisplayName(),   present) for name in self.device_manager.Devices()]
    
    # def open(self):
    #     """Open the camera device.

    #     After execution of this method the camera is ready
    #     to deliver frames.        

    #     Returns
    #     -------
    #     successful : bool
    #         True if the device was opened successfully.                     
    #     """

    #     self.name = "IDS UI326xCP-M (IDS/UI326xCP-M/4103712875-0)"
    #     # self.name = "ABCDEF"
    #     try:      
    #         self.device_manager.Update()
    #         count=0
    #         for name in self.device_manager.Devices():
    #             print(name.DisplayName())
    #             if name.DisplayName() == self.name:
                    
    #                 self.device = self.device_descriptor[count].OpenDevice(ids_peak.DeviceAccessType_Control)
    #                 print(name.DisplayName)
    #                 self.node_map_remote_device = self.device.RemoteDevice().NodeMaps()[0]
    #                 self.datastream = self.device.DataStreams()[0].OpenDataStream() 
                    
    #                 #set the pixelformat for used ids cameras to Mono12
    #                 self.node_map_remote_device.FindNode("PixelFormat").SetCurrentEntry("Mono12") 
    #                 return True
    #             count+=1
    #         return False
                
    #     except Exception: 
    #         return False



    def open(self):

        self.name = "IDS UI326xCP-M (IDS/UI326xCP-M/4103712875-1)"

        try:
            self.device_manager.Update()        
            self.device_descriptors = self.device_manager.Devices()
            count=0
            for name in self.device_manager.Devices():
                
                
                if name.DisplayName() == self.name:
                    # 
                    self.device = self.device_manager.Devices()[count].OpenDevice(ids_peak.DeviceAccessType_Control)
                    

                    self.node_map_remote_device = self.device.RemoteDevice().NodeMaps()[0]
                    #set the pixelformat for used ids cameras to Mono12
                    self.node_map_remote_device.FindNode("PixelFormat").SetCurrentEntry("Mono12")

                    return True
                # 
                count+=1
                                
                
            return False
                
        except TypeError: #Error-type change to ImagingSourceError
            return False
        

    def open_test(self, counter:int):

        # try:
        #     self.device = self.device_descriptors[0].OpenDevice(ids_peak.DeviceAccessType_Control)
        #     print("Opened Device: " + self.device.DisplayName())
        #     self.node_map_remote_device = self.device.RemoteDevice().NodeMaps()[0]

        try:
            self.device = self.device_descriptors[counter].OpenDevice(ids_peak.DeviceAccessType_Control)
            print("Opened Device: " + self.device.DisplayName())
            self.node_map_remote_device = self.device.RemoteDevice().NodeMaps()[0]

        except TypeError: #Error-type change to ImagingSourceError
            return False

        return True
    
    def close(self):
        """Closes the camera. For IDS cameras the reference to the object must be destroy, 
        by either going out-of-scope or by explicitly overwriting the variable."""
        self.device = None 


    
    def set_mode_test_image(self):
        #needed changes to use Software trigger
        self.node_map_remote_device.FindNode("TriggerSelector").SetCurrentEntry("ExposureStart")
        self.node_map_remote_device.FindNode("TriggerMode").SetCurrentEntry("On")
        self.node_map_remote_device.FindNode("TriggerSource").SetCurrentEntry("Software")

        #PixelFormat of camera ids 3260CP-M-GL Rev.2 is printed in this line  
        self.node_map_remote_device.FindNode("PixelFormat").SetCurrentEntry("Mono12") 
        

        #Binning and Decimation has "uEye" as value, which is controled by uEye decimation (subsampling)
        # self.node_map_remote_device.FindNode("BinningSelector").CurrentEntry().SymbolicValue()
        # self.node_map_remote_device.TryFindNode("DecimationSelector").CurrentEntry()

        #uEye decimation (subsampling) and Binning Preset can be obtained by
        # self.node_map_remote_device.FindNode("UEyeImageFormatPresetBinningX").Value()
        # self.node_map_remote_device.FindNode("UEyeImageFormatPresetBinningY").Value()
        # self.node_map_remote_device.FindNode("UEyeImageFormatPresetDecimationX").Value()
        # self.node_map_remote_device.FindNode("UEyeImageFormatPresetDecimationY").Value()

        #FrameRate
        self.node_map_remote_device.FindNode("AcquisitionFrameRate").Value()
        self.node_map_remote_device.FindNode("AcquisitionFrameRate").Minimum()
        self.node_map_remote_device.FindNode("AcquisitionFrameRate").Maximum()

    def get_frame_rate(self):
        return self.node_map_remote_device.FindNode("AcquisitionFrameRate").Value(), self.node_map_remote_device.FindNode("AcquisitionFrameRate").Minimum(), self.node_map_remote_device.FindNode("AcquisitionFrameRate").Maximum()

    def get_exposure(self):
        """Return the exposure time in milliseconds set in the camera."""
        return self.node_map_remote_device.FindNode("ExposureTime").Value()

    def set_exposure(self):
        """Set the exposure time."""
        self.node_map_remote_device.FindNode("ExposureTime").SetValue(self.exposure)

    def get_exposure_limits(self):
        """Return the minimum and maximum exposure time supported.
        
        Returns
        ------
        min_exposure, max_exposure : float
            Shortest and longest exposure times in milliseconds
        """        
        return self.node_map_remote_device.FindNode("ExposureTime").Minimum() , self.node_map_remote_device.FindNode("ExposureTime").Maximum()
        
    def get_binning(self):
        """IDS cameras support binning, even in vertical AND horizontal direction.""" #TODO: Redo the comment if this is clear

        self.binning_vertical = self.node_map_remote_device.FindNode("BinningVertical").Value()
        self.binning_horizontal = self.node_map_remote_device.FindNode("BinningHorizontal").Value()
        print(self.node_map_remote_device.FindNode("BinningVertical").Maximum())
        print(self.node_map_remote_device.FindNode("BinningHorizontal").Maximum())

        return self.binning_vertical,self.binning_horizontal 
    
    # def set_binning(self,binning_vertical:int,binning_horizontal:int):
    #     #binning function for ViPErLEED only has one general binning function, not vertical and horizontal factors -> different function 
    #     self.node_map_remote_device.FindNode("BinningVertical").SetValue(binning_vertical)
    #     self.node_map_remote_device.FindNode("BinningHorizontal").SetValue(binning_horizontal)
    #     return

    def get_frame_rate(self):
        """Return the number of frames delivered per second"""
        return self.node_map_remote_device.FindNode("AcquisitionFrameRate").Value() 

    def extra_delay(self):
        return 1 / self.get_frame_rate() , 1 / self.get_frame_rate() * 10**6
    
    def get_gain(self):
        """Get the gain in ... from camera""" #TODO: check if dB is correct
        return self.node_map_remote_device.FindNode("Gain").Value()
    
    def set_gain(self):
        """Set the gain of the camera in ...""" #TODO: check if dB is correct
        self.node_map_remote_device.FindNode("Gain").SetValue(self.gain)

    def get_gain_limits(self):
        """Returns the minimum and maximum gains supported.
        
        Returns
        ------
        min_gain, max_gain : float

        """
        gain_min = self.node_map_remote_device.FindNode("Gain").Minimum()
        gain_max = self.node_map_remote_device.FindNode("Gain").Maximum()
        return gain_min , gain_max
    

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
        roi_x = self.node_map_remote_device.FindNode("OffsetX").Value()
        roi_y = self.node_map_remote_device.FindNode("OffsetY").Value()
        roi_width = self.node_map_remote_device.FindNode("Width").Value()
        roi_height = self.node_map_remote_device.FindNode("Height").Value()

        return roi_x, roi_y, roi_width, roi_height

    # def get_roi_size_limits(self):
    #     """Return minimum, maximum and granularity of the ROI.

    #     Returns
    #     -------
    #     roi_min : tuple
    #         Two elements, both integers, corresponding to the
    #         minimum width and minimum height
    #     roi_max : tuple
    #         Two elements, both integers, corresponding to the
    #         maximum width and maximum height
    #     roi_increments : tuple
    #         Two elements, both integers, corresponding to the
    #         minimum allowed increments for width and height of
    #         the region of interest
    #     roi_offset_increments : tuple
    #         Two elements, both integers, corresponding to the
    #         minimum allowed increments for the horizontal and
    #         vertical position of the roi.
    #     """

    #     roi_min = tuple(self.node_map_remote_device.FindNode("OffsetX").Minimum(), self.node_map_remote_device.FindNode("OffsetY").Minimum())
    #     roi_max = tuple( self.node_map_remote_device.FindNode("OffsetX").Maximum(),  self.node_map_remote_device.FindNode("OffsetY").Maximum())
    #     roi_increments = tuple(self.node_map_remote_device.FindNode("OffsetX").Increment(), self.node_map_remote_device.FindNode("OffsetY").Increment())

    #     return roi_min, roi_max, roi_increments, (2,2)


    def get_roi_size_limits(self):
        """Return minimum, maximum and granularity of the ROI.

        Returns
        -------
        roi_min : tuple
            Two elements, both integers, corresponding to the
            minimum width and minimum height
        roi_max : tuple
            Two elements, both integers, correspeonding to the
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
        #https://www.1stvision.com/cameras/IDS/IDS-manuals/en/program-set-roi.html
        roi_min = (self.node_map_remote_device.FindNode("Width").Minimum(), self.node_map_remote_device.FindNode("Height").Minimum())
        roi_max = (self.node_map_remote_device.FindNode("Width").Maximum(), self.node_map_remote_device.FindNode("Height").Maximum())

        #roi_min = (self.remote_node_map.FindNode("OffsetX").Minimum(), self.remote_node_map.FindNode("OffsetY").Minimum())
        #roi_max = ( self.remote_node_map.FindNode("OffsetX").Maximum(),  self.remote_node_map.FindNode("OffsetY").Maximum())
        roi_increments = (self.node_map_remote_device.FindNode("Width").Increment(), self.node_map_remote_device.FindNode("Height").Increment())
        roi_offset_increments = (self.node_map_remote_device.FindNode("OffsetX").Increment(), self.node_map_remote_device.FindNode("OffsetY").Increment())

        return roi_min, roi_max, roi_increments, roi_offset_increments
    
    def multi_mode(self):
        print(self.node_map_remote_device.TryFindNode("AcquisitionMode").CurrentEntry().SymbolicValue())
        self.node_map_remote_device.TryFindNode("AcquisitionMode").SetCurrentEntry("SingleFrame")
        print(self.node_map_remote_device.TryFindNode("AcquisitionMode").CurrentEntry().SymbolicValue())    


    def get_mode(self):
        """Return the mode set in the camera.

        Returns:
        -------
        mode : {'live', 'triggered'}
            The mode the camera is operating in.
            Continuous (= live): Images are captured until stopped with the AcquisitionStop command
            SingleFrame (= triggered): One image is captured
            'triggered' is asynchronous: the camera returns a frame
            only when asked by self.trigger_now().

        Another possible AcquisitionMode a IDS camera can use is MultiFrame (tested cameras can't support this mode)
        MultiFrame: Number of images specified by AcquisitionFrameCount is captured. only supported by uEye+ cameras (GV and U3 models) #tested cameras didn't support this AcquisitionMode
        """

        return 'triggered' if self.node_map_remote_device.FindNode("AcquisitionMode").CurrentEntry().SymbolicValue() != "Continuous" else "live"

    def set_mode(self):
        """Set the camera mode""" 
        if self.node_map_remote_device.FindNode("AcquisitionMode").CurrentEntry().SymbolicValue() == "SingleFrame":
            return True
        else:
            self.node_map_remote_device.FindNode("AcquisitionMode").SetCurrentEntry("Continuous")
        return


    def reset(self):
        """Reset the camera to factory default settings."""
        self.node_map_remote_device.FindNode("ResetToFactoryDefaults").Execute()
        #Check if the command has finished before you continue
        self.node_map_remote_device.FindNode("ResetToFactoryDefaults").WaitUntilDone()

    def get_n_frames(self):
        """Return zero as the camera does not support frame averaging."""
        return 0
    
    def supports_trigger_burst(self):
        'Function already exist in abc.py'
        try:
            self.node_map_remote_device.TryFindNode("AcquisitionMode").SetCurrentEntry("MultiFrame")
        except:
            return False

    def is_running(self):
        """Return whether the camera is currently running.""" #TODO:
        return self.datastream.NodeMaps()[0].FindNode("StreamIsGrabbing").Value()
        #return self.node_map_remote_device.FindNode("SensorState").CurrentEntry().SymbolicValue() 

    def acquisition(self):
        """steps to enable an acquisition of an image"""
        self.datastream = self.device.DataStreams()[0].OpenDataStream()
  
        #Clear all old buffers
        for buffer in self.datastream.AnnouncedBuffers():
            self.datastream.RevokeBuffer(buffer)

        self.payload_size = self.node_map_remote_device.FindNode("PayloadSize").Value()

        #Number of minimum required buffers
        self.num_buffers_min_required = self.datastream.NumBuffersAnnouncedMinRequired()

        #Allocate buffers

        for count in range(self.num_buffers_min_required):
            self.buffer = self.datastream.AllocAndAnnounceBuffer(self.payload_size)
            self.datastream.QueueBuffer(self.buffer)
            
        
        self.datastream.StartAcquisition()
        self.node_map_remote_device.FindNode("AcquisitionStart").Execute()
        #Check if the command has finished before you continue (optional)
        self.node_map_remote_device.FindNode("AcquisitionStart").WaitUntilDone()
        
    


    def single_image(self):
        self.node_map_remote_device.FindNode("TriggerSelector").SetCurrentEntry("ExposureStart")
        self.node_map_remote_device.FindNode("TriggerMode").SetCurrentEntry("On")
        self.node_map_remote_device.FindNode("TriggerSource").SetCurrentEntry("Software")
        #image trigger
        self.node_map_remote_device.FindNode("TriggerSoftware").Execute()
        self.node_map_remote_device.FindNode("TriggerSoftware").WaitUntilDone()
        print(self.buffer.HasImage())
        

        self.buffer = self.datastream.WaitForFinishedBuffer(5000)
        print(self.buffer.HasImage())
        
        raw_image = ids_ipl_extension.BufferToImage(self.buffer)
        self.datastream.QueueBuffer(self.buffer)

        picture = raw_image.get_numpy_2D_16().byteswap(True)
        
        image = Image.fromarray(picture)
        image.save("pic.png")
        image.show()
        
        

    def exceptions(self):
        """Return a tuple of camera exceptions.

        Returns
        -------
        exceptions : tuple
            Each element is an Exception subclass of exceptions
            that the camera may raise in case internal driver
            errors occur.
        """
        return tuple( cls for _, cls in inspect.getmembers(ids_peak, inspect.isclass) if issubclass(cls, Exception) ) #check if this works or not
        
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

        width = self.node_map_remote_device.FindNode("Width").Value()
        height = self.node_map_remote_device.FindNode("Height").Value()

        pixel_format = self.node_map_remote_device.FindNode("PixelFormat").CurrentEntry().SymbolicValue()

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

        pixel_format = self.node_map_remote_device.FindNode("PixelFormat").CurrentEntry().SymbolicValue()

        #this if segment is only for monochromatic ids cameras and could be densed down
        # if this way of calculating the pixel_min and pixel_max can't be checked for Mono12p and Mono10p ()
        if "16" in pixel_format: #Mono16
            n_bytes = 2
            dyn_range = 16
        elif "12p" in pixel_format: #Mono12p 
            n_bytes = 2  
            dyn_range = 12
        elif "10p" in pixel_format: #Mono10p
            n_bytes = 2
            dyn_range = 10
        elif "12" in pixel_format:  #Mono12
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

    def black_level(self):
        self.node_map_remote_device.FindNode("BlackLevel").SetValue(1.0)        
        return self.node_map_remote_device.FindNode("PixelFormat").CurrentEntry().SymbolicValue(), self.node_map_remote_device.FindNode("BlackLevel").Value() , self.node_map_remote_device.FindNode("BlackLevel").Minimum() , self.node_map_remote_device.FindNode("BlackLevel").Maximum()
        



ids_1 = Test_ids()
ids_1.__init__()

# print(ids_1.list_devices())
ids_1.open()

# ids_1.multi_mode()

ids_1.acquisition()

ids_1.single_image()
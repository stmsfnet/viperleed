import ids_peak.ids_peak as ids_peak
from matplotlib import pyplot as plt
import ids_peak.ids_peak_ipl_extension as ids_ipl_extension
import ids_peak_ipl.ids_peak_ipl as ids_ipl
from viperleed.gui.measure.classes.abc import SettingsInfo
from plotnine import ggplot, aes, geom_line




class Test_ids:
    def __init__(self):

        ids_peak.Library.Initialize()
        self.device_manager = ids_peak.DeviceManager.Instance()
        self.device_manager.Update()
        self.device_descriptors = self.device_manager.Devices()
        

    def list_devices(self):

        present = True
        return  [SettingsInfo(name.DisplayName(),   present) for name in self.device_descriptors]
    
    def open(self):
        
        try:
            self.device = self.device_descriptors[0].OpenDevice(ids_peak.DeviceAccessType_Control)
            print("Opened Device: " + self.device.DisplayName())
            self.node_map_remote_device = self.device.RemoteDevice().NodeMaps()[0]

        # try:
        #     self.device = self.device_descriptors[counter].OpenDevice(ids_peak.DeviceAccessType_Control)
        #     print("Opened Device: " + self.device.DisplayName())
        #     self.node_map_remote_device = self.device.RemoteDevice().NodeMaps()[counter]

        except TypeError: #Error-type change to ImagingSourceError
            return False

        return True
    
    def close(self):
        self.device = None
    
    def set_mode(self):
        #needed changes to use Software trigger
        self.node_map_remote_device.FindNode("TriggerSelector").SetCurrentEntry("ExposureStart")
        self.node_map_remote_device.FindNode("TriggerMode").SetCurrentEntry("On")
        self.node_map_remote_device.FindNode("TriggerSource").SetCurrentEntry("Software")

        #PixelFormat of camera ids 3260CP-M-GL Rev.2 is printed in this line  


        self.node_map_remote_device.FindNode("PixelFormat").SetCurrentEntry("Mono12")
        print(self.node_map_remote_device.FindNode("PixelFormat").CurrentEntry().SymbolicValue())        

    def acquisition(self):

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

        #image trigger
        self.node_map_remote_device.FindNode("TriggerSoftware").Execute()
        self.node_map_remote_device.FindNode("TriggerSoftware").WaitUntilDone()

        self.buffer = self.datastream.WaitForFinishedBuffer(5000)

        self.raw_image = ids_ipl_extension.BufferToImage(self.buffer)
        # self.mono_image = self.raw_image.ConvertTo(ids_ipl.PixelFormatName_Mono)
        # if camera is mono, than this line should be useless -> line 52 in set_mode() 

        self.datastream.QueueBuffer(self.buffer)

        # self.picture = self.mono_image.get_numpy_3D()
        # self.picture.save
        return 

ids_1 = Test_ids()
# print(ids_1.list_devices())
ids_1.open()
ids_1.set_mode()
ids_1.acquisition()
ids_1.single_image()

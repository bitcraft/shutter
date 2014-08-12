"""
# piggyphoto.py
# Copyright (C) 2010 Alex Dumitrache
# Based on:
# - a small code example by Mario Boikov,
#   http://pysnippet.blogspot.com/2009/12/when-ctypes-comes-to-rescue.html
# - libgphoto2 Python bindings by David PHAM-VAN <david@ab2r.com>
# - ctypes_gphoto2.py by Hval Ulrich Niedermann <gp@n-dimensional.de>

modifications: leif theden, 2014
- removed string module dependency
- pep8
- stability
- cameraFile Sanity
- modern property declarations
- documentation
- slight simplification
- get_data method on CameraFile  --  very useful!

incorporated patches from:
  chunkerchunker's fork: YesVideo:master
  jacobmarble's fork

"""
import re
import ctypes
import ctypes.util
import os
import time
import platform

# python 2/3 interop
from six.moves import range


# This is run if gp_camera_init returns -60 (Could not lock the device)
unmount_cmd = None
if platform.system() == 'Darwin':
    unmount_cmd = 'killall PTPCamera'
else:
    unmount_cmd = 'gvfs-mount -s gphoto2'

libgphoto2dll = ctypes.util.find_library('gphoto2')
gp = ctypes.CDLL(libgphoto2dll)
gp.gp_context_new.restype = ctypes.POINTER(ctypes.c_char)
context = gp.gp_context_new()

PTR = ctypes.pointer

#cdef extern from "gphoto2/gphoto2-port-version.h":
#  ctypedef enum GPVersionVerbosity:
GP_VERSION_SHORT = 0
GP_VERSION_VERBOSE = 1

#cdef extern from "gphoto2/gphoto2-abilities-list.h":
#  ctypedef enum CameraDriverStatus:
GP_DRIVER_STATUS_PRODUCTION = 0
GP_DRIVER_STATUS_TESTING = 1
GP_DRIVER_STATUS_EXPERIMENTAL = 2
GP_DRIVER_STATUS_DEPRECATED = 3

#  ctypedef enum CameraOperation:
GP_OPERATION_NONE = 0
GP_OPERATION_CAPTURE_IMAGE = 1
GP_OPERATION_CAPTURE_VIDEO = 2
GP_OPERATION_CAPTURE_AUDIO = 3
GP_OPERATION_CAPTURE_PREVIEW = 4
GP_OPERATION_CONFIG = 5

#  ctypedef enum CameraFileOperation:
GP_FILE_OPERATION_NONE = 0
GP_FILE_OPERATION_DELETE = 1
GP_FILE_OPERATION_PREVIEW = 2
GP_FILE_OPERATION_RAW = 3
GP_FILE_OPERATION_AUDIO = 4
GP_FILE_OPERATION_EXIF = 5

#  ctypedef enum CameraEventType:
GP_EVENT_UNKNOWN = 0
GP_EVENT_TIMEOUT = 1
GP_EVENT_FILE_ADDED = 2
GP_EVENT_FOLDER_ADDED = 3
GP_EVENT_CAPTURE_COMPLETE = 4

#  ctypedef enum CameraFolderOperation:
GP_FOLDER_OPERATION_NONE = 0
GP_FOLDER_OPERATION_DELETE_ALL = 1
GP_FOLDER_OPERATION_PUT_FILE = 2
GP_FOLDER_OPERATION_MAKE_DIR = 3
GP_FOLDER_OPERATION_REMOVE_DIR = 4

#cdef extern from "gphoto2/gphoto2-port-info-list.h":
#  ctypedef enum GPPortType:
GP_PORT_NONE = 0
GP_PORT_SERIAL = 1
GP_PORT_USB = 2

# gphoto constants
# Defined in 'gphoto2-port-result.h'
GP_OK = 0
# CameraCaptureType enum in 'gphoto2-camera.h'
GP_CAPTURE_IMAGE = 0
# CameraFileType enum in 'gphoto2-file.h'
GP_FILE_TYPE_NORMAL = 1


class ShutterError(Exception):
    def __init__(self, result, message):
        self.result = result
        self.message = message

    def __str__(self):
        return self.message + ' (' + str(self.result) + ')'


def gp_library_version(verbose=True):
    gp.gp_library_version.restype = ctypes.POINTER(ctypes.c_char_p)
    if not verbose:
        arr_text = gp.gp_library_version(GP_VERSION_SHORT)
    else:
        arr_text = gp.gp_library_version(GP_VERSION_VERBOSE)

    v = ''
    for s in arr_text:
        if s is None:
            break
        v += '%s\n' % s
    return v


def check(result):
    if result < 0:
        gp.gp_result_as_string.restype = ctypes.c_char_p
        message = gp.gp_result_as_string(result)
        raise ShutterError(result, message)
    return result


def check_unref(result, camfile):
    if result != 0:
        gp.gp_file_unref(camfile.pointer)
        gp.gp_result_as_string.restype = ctypes.c_char_p
        message = gp.gp_result_as_string(result)
        raise ShutterError(result, message)


class CameraFilePathStruct(ctypes.Structure):
    _fields_ = [('name', (ctypes.c_char * 128)),
                ('folder', (ctypes.c_char * 1024))]


class CameraTextStruct(ctypes.Structure):
    _fields_ = [('text', (ctypes.c_char * (32 * 1024)))]


class CameraAbilitiesStruct(ctypes.Structure):
    _fields_ = [('model', (ctypes.c_char * 128)),
                ('status', ctypes.c_int),
                ('port', ctypes.c_int),
                ('speed', (ctypes.c_int * 64)),
                ('operations', ctypes.c_int),
                ('file_operations', ctypes.c_int),
                ('folder_operations', ctypes.c_int),
                ('usb_vendor', ctypes.c_int),
                ('usb_product', ctypes.c_int),
                ('usb_class', ctypes.c_int),
                ('usb_subclass', ctypes.c_int),
                ('usb_protocol', ctypes.c_int),
                ('library', (ctypes.c_char * 1024)),
                ('id', (ctypes.c_char * 1024)),
                ('device_type', ctypes.c_int),
                ('reserved2', ctypes.c_int),
                ('reserved3', ctypes.c_int),
                ('reserved4', ctypes.c_int),
                ('reserved5', ctypes.c_int),
                ('reserved6', ctypes.c_int),
                ('reserved7', ctypes.c_int),
                ('reserved8', ctypes.c_int)]


class PortInfoStruct(ctypes.Structure):
    _fields_ = [
        ('type', ctypes.c_int),  # enum is 32 bits on 32 and 64 bit Linux
        ('name', (ctypes.c_char * 64)),
        ('path', (ctypes.c_char * 64)),
        ('library_filename', (ctypes.c_char * 1024))
    ]
    
class PortInfoStruct(ctypes.Structure):
    _fields_ = [
        ('type', ctypes.c_int),  # enum is 32 bits on 32 and 64 bit Linux
        ('name', (ctypes.c_char)),
        ('path', (ctypes.c_char)),
        ('library_filename', (ctypes.c_char))
    ]


class Camera(object):
    """ Object representing a camera attached to the system.

    The abilities of this type of camera are stored in a CameraAbility object.
    This is a thin ctypes wrapper about libgphoto2 Camera, with a few tweaks.
    """
    def __init__(self, regex=None):            
        self._ptr = ctypes.c_void_p()
        check(gp.gp_camera_new(PTR(self._ptr)))
        if regex:
            cl = CameraList(autodetect=True)
            for name, path in cl.as_list():
                m = regex.search(name.lower())
                if m:
                    abl = CameraAbilities()
                    al = CameraAbilitiesList()
                    # get the port
                    pi = PortInfoList()
                    index = pi.lookup_path(path)
                    port = pi.get_info(index)
                    # get the model
                    model = al.lookup_model(name)
                    al.get_abilities(model, abl)
                    # set our attributes
                    self.abilities = abl
                    self.port_info = port

        val = gp.gp_camera_init(self._ptr, context)
        if val == -60:
            raise ShutterError(val, "cannot init camera")
        check(val)

    def __del__(self):
        check(gp.gp_camera_exit(self._ptr))
        check(gp.gp_camera_unref(self._ptr))

    def close(self):
        """
        Close connection to camera.
        """
        check(gp.gp_camera_exit(self._ptr, context))

    @property
    def pointer(self):
        return self._ptr

    @property
    def summary(self):
        """ Returns information about the camera.

        Returns:
            summary (dict): information about the camera
        """
        txt = CameraTextStruct()
        check(gp.gp_camera_get_summary(self._ptr, PTR(txt), context))
        r = dict()
        for l in txt.text.split('\n'):
            try:
                k, v = l.split(':')
            except ValueError:
                continue
            r[k.strip()] = v.strip()
        return r

    @property
    def about(self):
        """ Get information about the camera driver

        Returns:
            info (str): Typically, is author, acknowledgements, etc.
        """
        txt = CameraTextStruct()
        check(gp.gp_camera_get_about(self._ptr, PTR(txt), context))
        return txt.text

    @property
    def abilities(self):
        ab = CameraAbilities()
        check(gp.gp_camera_get_abilities(self._ptr, PTR(ab.pointer)))
        return ab

    @abilities.setter
    def abilities(self, ab):
        check(gp.gp_camera_set_abilities(self._ptr, ab.pointer))

    @property
    def port_info(self):
        pi = PortInfo()
        check(gp.gp_camera_get_port_info(self._ptr, PTR(pi.pointer)))
        return pi

    @port_info.setter
    def port_info(self, info):
        check(gp.gp_camera_set_port_info(self._ptr, info.pointer))

    def capture_image(self, destpath=None):
        """ Capture an image and store it to the camera.

        Kwargs:
            path (str): If specified, file will be saved here

        Returns:
            path (str): where the file was saved, either on camera or host

        Raises:
            ShutterError

        If destpath is passed, then the image will be saved on the host.
        If saved the the camera (destpath not passed), then the path returned
        from this function will be relative to the camera's internal memory or
        another storage device in the camera (SD card, etc.)
        """
        path = CameraFilePathStruct()
        f = gp.gp_camera_capture
        val = f(self._ptr, GP_CAPTURE_IMAGE, PTR(path), context)
        check(val)

        if destpath:
            self.download_file(path.folder, path.name, destpath)
            return destpath
        else:
            return os.path.join(path.folder, path.name)

    def capture_preview(self, destpath=None):
        """ Captures a preview image that won't be stored on the camera

        Kwargs:
            path (str): If specified, file will be saved here

        Returns:
            CameraFile object

        Raises:
            ShutterError

        The preview image format varies in different camera models.  Generally,
        the image will not have the full detail/resolution of the camera.
        """
        cfile = CameraFile()
        f = gp.gp_camera_capture_preview
        check(f(self._ptr, cfile.pointer, context))

        if destpath:
            cfile.save(destpath)

        return cfile

    def download_file(self, srcfolder, srcfilename, destpath):
        """ Download a file from the camera's filesystem.
        """
        cfile = CameraFile(self._ptr, srcfolder, srcfilename)
        cfile.save(destpath)
        check(gp.gp_file_unref(cfile.pointer))

    def list_folders(self, path="/"):
        """ List folders in path.
        """
        l = CameraList()
        f = gp.gp_camera_folder_list_folders
        check(f(self._ptr, str(path), l.pointer, context))
        return l.as_list()

    def list_files(self, path="/"):
        """ List files in path.
        """
        l = CameraList()
        f = gp.gp_camera_folder_list_files
        check(f(self._ptr, str(path), l.pointer, context))
        return l.as_list()

    def wait_for_event(self, timeout=1000):
        data = ctypes.c_char_p()
        t = ctypes.c_int()
        f = gp.gp_camera_wait_for_event
        val = check(f(self._ptr, timeout, PTR(t), PTR(data), context))
        return val


class CameraList(object):
    def __init__(self, autodetect=False):
        self._ptr = ctypes.c_void_p()
        check(gp.gp_list_new(PTR(self._ptr)))
        if autodetect:
            gp.gp_camera_autodetect(self._ptr, context)

    def __del__(self):
        check(gp.gp_list_unref(self._ptr))

    @property
    def pointer(self):
        return self._ptr

    def as_list(self):
        return [(self.get_name(i), self.get_value(i))
                for i in range(self.count())]

    def as_dict(self):
        return dict(self.as_list())

    def reset(self):
        check(gp.gp_list_reset(self._ptr))

    def append(self, name, value):
        check(gp.gp_list_append(self._ptr, str(name), str(value)))

    def sort(self):
        check(gp.gp_list_sort(self._ptr))

    def count(self):
        return check(gp.gp_list_count(self._ptr))

    def find_by_name(self, name):
        index = ctypes.c_int()
        check(gp.gp_list_find_by_name(self._ptr, PTR(index), str(name)))
        return index.value

    def get_name(self, index):
        name = ctypes.c_char_p()
        check(gp.gp_list_get_name(self._ptr, int(index), PTR(name)))
        return name.value

    def get_value(self, index):
        value = ctypes.c_char_p()
        check(gp.gp_list_get_value(self._ptr, int(index), PTR(value)))
        return value.value

    def set_name(self, index, name):
        check(gp.gp_list_set_name(self._ptr, int(index), str(name)))

    def set_value(self, index, value):
        check(gp.gp_list_set_value(self._ptr, int(index), str(value)))

    def __str__(self):
        header = "cameraList object with %d elements:\n" % self.count()
        contents = ["%d: (%s, %s)" % (i, self.get_name(i), self.get_value(i))
                    for i in range(self.count())]

        return header + '\n'.join(contents)


class CameraFile(object):
    """
    Abstract data container for camera image files.
    """
    def __init__(self, cam=None, srcfolder=None, srcfilename=None):
        self._ptr = ctypes.c_void_p()
        check(gp.gp_file_new(PTR(self._ptr)))
        if cam:
            f = gp.gp_camera_file_get
            check_unref(f(cam, srcfolder, srcfilename, GP_FILE_TYPE_NORMAL,
                          self._ptr, context), self)

    def __del__(self):
        check(gp.gp_file_unref(self._ptr))

    @property
    def pointer(self):
        return self._ptr

    def get_data(self):
        """
        Return a Python string that represents the data
        """
        data = ctypes.c_char_p()
        size = ctypes.c_ulong()
        check(gp.gp_file_get_data_and_size(self._ptr, PTR(data), PTR(size)))
        string = ctypes.string_at(data, int(size.value))
        return string

    def save(self, filename=None):
        if filename is None:
            filename = self.name
        check(gp.gp_file_save(self._ptr, filename))

    @property
    def name(self):
        name = ctypes.c_char_p()
        check(gp.gp_file_get_name(self._ptr, PTR(name)))
        return name.value

    @name.setter
    def name(self, value):
        check(gp.gp_file_set_name(self._ptr, str(value)))


class CameraAbilities(object):
    def __init__(self):
        self._ptr = CameraAbilitiesStruct()

    def __repr__(self):
        return "Model : %s\nStatus : %d\nPort : %d\nOperations : %d\nFile Operations : %d\nFolder Operations : %d\nUSB (vendor/product) : 0x%x/0x%x\nUSB class : 0x%x/0x%x/0x%x\nLibrary : %s\nId : %s\n" % (
            self._ptr.model, self._ptr.status, self._ptr.port,
            self._ptr.operations,
            self._ptr.file_operations, self._ptr.folder_operations,
            self._ptr.usb_vendor, self._ptr.usb_product, self._ptr.usb_class,
            self._ptr.usb_subclass, self._ptr.usb_protocol, self._ptr.library,
            self._ptr.id)

    @property
    def pointer(self):
        return self._ptr

    model = property(lambda self: self._ptr.model, None)
    status = property(lambda self: self._ptr.status, None)
    port = property(lambda self: self._ptr.port, None)
    operations = property(lambda self: self._ptr.operations, None)
    file_operations = property(lambda self: self._ptr.file_operations, None)
    folder_operations = property(lambda self: self._ptr.folder_operations, None)
    usb_vendor = property(lambda self: self._ptr.usb_vendor, None)
    usb_product = property(lambda self: self._ptr.usb_product, None)
    usb_class = property(lambda self: self._ptr.usb_class, None)
    usb_subclass = property(lambda self: self._ptr.usb_subclass, None)
    usb_protocol = property(lambda self: self._ptr.usb_protocol, None)
    library = property(lambda self: self._ptr.library, None)
    id = property(lambda self: self._ptr.id, None)


class PortInfo(object):
    def __init__(self):
        self._ptr = PortInfoStruct()

    @property
    def pointer(self):
        return self._ptr

    type = property(lambda self: self._ptr.type, None)
    name = property(lambda self: self._ptr.name, None)
    path = property(lambda self: self._ptr.path, None)
    library_filename = property(lambda self: self._ptr.library_filename, None)


class CameraAbilitiesList(object):
    _static_l = None

    def __init__(self):
        if CameraAbilitiesList._static_l is None:
            CameraAbilitiesList._static_l = ctypes.c_void_p()
            check(gp.gp_abilities_list_new(PTR(CameraAbilitiesList._static_l)))
            check(gp.gp_abilities_list_load(CameraAbilitiesList._static_l,
                                            context))
        self._l = CameraAbilitiesList._static_l

    @property
    def pointer(self):
        return self._l

    def detect(self, il, l):
        f = gp.gp_abilities_list_detect
        check(f(self._l, il.pointer, l.pointer, context))

    def lookup_model(self, model):
        f = gp.gp_abilities_list_lookup_model
        return check(f(self._l, model))

    def get_abilities(self, model_index, ab):
        f = gp.gp_abilities_list_get_abilities
        return check(f(self._l, model_index, PTR(ab.pointer)))


class PortInfoList(object):
    _static_l = None

    @property
    def pointer(self):
        return self._l

    def __init__(self):
        if PortInfoList._static_l is None:
            PortInfoList._static_l = ctypes.c_void_p()
            check(gp.gp_port_info_list_new(PTR(PortInfoList._static_l)))
            check(gp.gp_port_info_list_load(PortInfoList._static_l))
        self._l = PortInfoList._static_l

    def count(self):
        c = gp.gp_port_info_list_count(self._l)
        check(c)
        return c

    def lookup_path(self, path):
        index = gp.gp_port_info_list_lookup_path(self._l, path)
        check(index)
        return index

    def get_info(self, path_index):
        info = PortInfo()
        check(gp.gp_port_info_list_get_info(self._l, path_index, PTR(info.pointer)))
        return info


if __name__ == '__main__':
    import shutter
    import re
    c = shutter.Camera(re.compile('canon'))
    c.capture_image()

"""
# piggyphoto.py
# Copyright (C) 2010 Alex Dumitrache
# Based on:
# - a small code example by Mario Boikov,
#   http://pysnippet.blogspot.com/2009/12/when-ctypes-comes-to-rescue.html
# - libgphoto2 Python bindings by David PHAM-VAN <david@ab2r.com>
# - ctypes_gphoto2.py by Hans Ulrich Niedermann <gp@n-dimensional.de>

modifications: leif theden, 2014
- removed string module dependency
- pep8
- stability
- cameraFile Sanity
- modern property declarations
- documentation
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

from .ptp import *

# python 2/3 interop
from six.moves import range


# Some functions return errors which can be fixed by retrying.
# For example, capture_preview on Canon 550D fails the first time, but
# subsequent calls are OK.
# Retries are performed on: camera.capture_preview, camera.capture_image and
# camera.init()
retries = 1

# This is run if gp_camera_init returns -60 (Could not lock the device)
# and retries >= 1.
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


def library_version(verbose=True):
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
        gp.gp_file_unref(camfile._cf)
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


class Camera(object):
    """
    Object representing a camera attached to the system.

    The abilities of this type of camera are stored in a CameraAbility object.
    This is a thin ctypes wrapper about libgphoto2 Camera, with a few tweaks.
    """

    def __init__(self):
        self._ptr = ctypes.c_void_p()
        check(gp.gp_camera_new(PTR(self._ptr)))

        ans = 0
        for i in range(1 + retries):
            ans = gp.gp_camera_init(self._ptr, context)
            if ans == 0:
                break
            elif ans == -60:
                os.system(unmount_cmd)
                time.sleep(1)
                raise ShutterError(ans, "cannot init camera")
        check(ans)

    def __del__(self):
        check(gp.gp_camera_exit(self._ptr))
        check(gp.gp_camera_unref(self._ptr))

    def _ref(self):
        """
        Increment the reference count of this camera.
        """
        check(gp.gp_camera_ref(self._ptr))

    def _unref(self):
        """
        Decrements the reference count of this camera.
        """
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
        txt = CameraTextStruct()
        check(gp.gp_camera_get_summary(self._ptr, PTR(txt), context))
        return txt.text

    @property
    def manual(self):
        txt = CameraTextStruct()
        check(gp.gp_camera_get_manual(self._ptr, PTR(txt), context))
        return txt.text

    @property
    def about(self):
        txt = CameraTextStruct()
        check(gp.gp_camera_get_about(self._ptr, PTR(txt), context))
        return txt.text

    @property
    def abilities(self):
        ab = CameraAbilities()
        check(gp.gp_camera_get_abilities(self._ptr, PTR(ab._ab)))
        return ab

    @abilities.setter
    def abilities(self, ab):
        check(gp.gp_camera_set_abilities(self._ptr, ab._ab))

    @property
    def port_info(self):
        raise NotImplementedError

    @port_info.setter
    def port_info(self, info):
        check(gp.gp_camera_set_port_info(self._ptr, info))

    def capture_image(self, destpath=None):
        """
        Capture an image and store it to the camera and path.
        """
        path = CameraFilePathStruct()
        ans = 0
        f = gp.gp_camera_capture
        for i in range(1 + retries):
            ans = f(self._ptr, GP_CAPTURE_IMAGE, PTR(path), context)
            if ans == 0:
                break
        check(ans)

        if destpath:
            self.download_file(path.folder, path.name, destpath)
        else:
            return path.folder, path.name

    def capture_preview(self, destpath=None):
        """
        Captures a preview that won't be stored on the camera but returned
        in supplied file.

        The preview file will not have the full detail/resolution of the camera.
        """
        #path = CameraFilePathStruct()
        cfile = CameraFile()

        ans = 0
        f = gp.gp_camera_capture_preview
        for i in range(1 + retries):
            ans = f(self._ptr, cfile.pointer, context)
            if ans == 0:
                break

        if destpath:
            cfile.save(destpath)
            cfile.free(destpath)
        else:
            return cfile

    def download_file(self, srcfolder, srcfilename, destpath):
        """
        Download a file from the camera.
        """
        cfile = CameraFile(self._ptr, srcfolder, srcfilename)
        cfile.save(destpath)
        gp.gp_file_unref(cfile._ptr)

    def trigger_capture(self):
        """
        Triggers capture of one image.
        """
        check(gp.gp_camera_trigger_capture(self._ptr, context))

    def wait_for_event(self, timeout):
        """
        Wait for an event from the camera. (Not Implemented)
        """
        raise NotImplementedError

    def list_folders(self, path="/"):
        """
        List folders in path.
        """
        l = CameraList()
        f = gp.gp_camera_folder_list_folders
        check(f(self._ptr, str(path), l.pointer, context))
        return l.as_list()

    def list_files(self, path="/"):
        """
        List files in path.
        """
        l = CameraList()
        f = gp.gp_camera_folder_list_files
        check(f(self._ptr, str(path), l.pointer, context))
        return l.as_list()

    def ptp_canon_eos_requestdevicepropvalue(self, prop):
        params = ctypes.c_void_p(self._ptr.value + 12)
        gp.ptp_generic_no_data(params, PTP_OC_CANON_EOS_RequestDevicePropValue,
                               1, prop)


class CameraList(object):
    def __init__(self, autodetect=False):
        self._ptr = ctypes.c_void_p()
        check(gp.gp_list_new(PTR(self._ptr)))

        if autodetect:
            if hasattr(gp, 'gp_camera_autodetect'):
                gp.gp_camera_autodetect(self._ptr, context)
            else:
                # this is for stable versions of gphoto <= 2.4.10.1
                xlist = CameraList()
                il = PortInfoList()
                il.count()
                al = CameraAbilitiesList()
                al.detect(il, xlist)

                # with libgphoto 2.4.8, sometimes one attached camera returns
                # one path "usb:" and sometimes two paths "usb:"
                # and "usb:xxx,yyy"
                good_list = []
                bad_list = []
                for i in xrange(xlist.count()):
                    model = xlist.get_name(i)
                    path = xlist.get_value(i)
                    #print model, path
                    if re.match(r'usb:\d{3},\d{3}', path):
                        good_list.append((model, path))
                    elif path == 'usb:':
                        bad_list.append((model, path))
                if len(good_list):
                    for model, path in good_list:
                        self.append(model, path)
                elif len(bad_list) == 1:
                    model, path = bad_list[0]
                    self.append(model, path)

                del al
                del il
                del xlist

    def __del__(self):
        check(gp.gp_list_free(self._ptr))

    def _ref(self):
        check(gp.gp_list_ref(self._ptr))

    def _unref(self):
        check(gp.gp_list_ref(self._ptr))

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
    def __init__(self, cam=None, srcfolder=None, srcfilename=None):
        self._ptr = ctypes.c_void_p()
        check(gp.gp_file_new(PTR(self._ptr)))
        if cam:
            f = gp.gp_camera_file_get
            check_unref(f(cam, srcfolder, srcfilename, GP_FILE_TYPE_NORMAL,
                          self._ptr, context), self)

    def __del__(self):
        self.free(None)

    @property
    def pointer(self):
        return self._ptr

    def free(self, filename):
        check(gp.gp_file_free(self._ptr))

    def get_data(self):
        """
        Return a Python string that represents the data
        """
        data = ctypes.c_char_p()
        size = ctypes.c_ulong()
        check(gp.gp_file_get_data_and_size(self._ptr, PTR(data), PTR(size)))
        return ctypes.string_at(data, int(size.value))

    def open(self, filename):
        check(gp.gp_file_open(PTR(self._ptr), filename))

    def save(self, filename=None):
        if filename is None:
            filename = self.name

        check(gp.gp_file_save(self._ptr, filename))

    def ref(self):
        check(gp.gp_file_ref(self._ptr))

    def unref(self):
        check(gp.gp_file_unref(self._ptr))

    def clean(self):
        check(gp.gp_file_clean(self._ptr))

    def copy(self, source):
        check(gp.gp_file_copy(self._ptr, source.pointer))

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
        self._ab = CameraAbilitiesStruct()

    def __repr__(self):
        return "Model : %s\nStatus : %d\nPort : %d\nOperations : %d\nFile Operations : %d\nFolder Operations : %d\nUSB (vendor/product) : 0x%x/0x%x\nUSB class : 0x%x/0x%x/0x%x\nLibrary : %s\nId : %s\n" % (
            self._ab.model, self._ab.status, self._ab.port, self._ab.operations,
            self._ab.file_operations, self._ab.folder_operations,
            self._ab.usb_vendor, self._ab.usb_product, self._ab.usb_class,
            self._ab.usb_subclass, self._ab.usb_protocol, self._ab.library,
            self._ab.id)

    model = property(lambda self: self._ab.model, None)
    status = property(lambda self: self._ab.status, None)
    port = property(lambda self: self._ab.port, None)
    operations = property(lambda self: self._ab.operations, None)
    file_operations = property(lambda self: self._ab.file_operations, None)
    folder_operations = property(lambda self: self._ab.folder_operations, None)
    usb_vendor = property(lambda self: self._ab.usb_vendor, None)
    usb_product = property(lambda self: self._ab.usb_product, None)
    usb_class = property(lambda self: self._ab.usb_class, None)
    usb_subclass = property(lambda self: self._ab.usb_subclass, None)
    usb_protocol = property(lambda self: self._ab.usb_protocol, None)
    library = property(lambda self: self._ab.library, None)
    id = property(lambda self: self._ab.id, None)


class CameraAbilitiesList(object):
    _static_l = None

    def __init__(self):
        if CameraAbilitiesList._static_l is None:
            CameraAbilitiesList._static_l = ctypes.c_void_p()
            check(gp.gp_abilities_list_new(PTR(CameraAbilitiesList._static_l)))
            check(gp.gp_abilities_list_load(CameraAbilitiesList._static_l,
                                            context))
        self._l = CameraAbilitiesList._static_l

    def detect(self, il, l):
        f = gp.gp_abilities_list_detect
        check(f(self._l, il.pointer, l.pointer, context))

    def lookup_model(self, model):
        f = gp.gp_abilities_list_lookup_model
        return check(f(self._l, model))

    def get_abilities(self, model_index, ab):
        f = gp.gp_abilities_list_get_abilities
        check(f(self._l, model_index, PTR(ab.pointer)))


class PortInfoList(object):
    _static_l = None

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
        info = PortInfoStruct()
        check(gp.gp_port_info_list_get_info(self._l, path_index, PTR(info)))
        return info
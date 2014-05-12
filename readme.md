shutter
=======

Shutter doesn't expose the entire libgphoto2 API, rather, it tries to create a
simple way to capture images from a camera.

Use libgphoto2 to control a tethered camera.
Fork of defunct project 'piggyphoto' by Alex Dumitrache

i've cleaned it up quiet a bit, and added patches that were left in pull
requests, but much is still untested

currently supported on linux and python 2.7


Use
---

    import shutter
    camera = shutter.Camera()
    camera.capture("file.jpg")

    data = camera.capture()
    data.save("file.jpg")


Supports
--------
- Capturing images, previews
- Probably more, but totally untested


Goals
-----
- python 3 support
- unit tests, someday
- remove all the cruft!
- more 'pythonic' interface


Supported Cameras
-----------------

http://www.gphoto.org/proj/libgphoto2/support.php
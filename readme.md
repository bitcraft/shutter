shutter
=======

Shutter doesn't expose the entire libgphoto2 API, rather, it tries to create a
simple way to capture images from a camera.

Use libgphoto2 to control a tethered camera.
Fork of defunct project 'piggyphoto' by Alex Dumitrache

I've cleaned it up quiet a bit, and added patches that were left in pull
requests, but much is still untested.

Currently supported on linux and python 3.4


Use
---

    # use the first camera detected on system
    import shutter
    camera = shutter.Camera()

    # capture and save an image
    camera.capture_image("file.jpg")

    # keep the image data
    data = camera.capture_image()
    data.save("file.jpg")

    # use regular expressions to search for a model
    import re
    camera = shutter.Camera(re.compile('canon'))


Supports
--------
- Capturing images, previews
- Gracefully handle multiple cameras (regex search)
- Probably more, but untested


Goals
-----
- unit tests, someday
- remove all the cruft!


Supported Cameras
-----------------

http://www.gphoto.org/proj/libgphoto2/support.php

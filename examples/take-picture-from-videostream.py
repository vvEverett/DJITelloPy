import cv2
from djitellopy.tello import Tello

tello = Tello("192.168.3.21")
tello.connect()

tello.streamon()
frame_read = tello.get_frame_read(port=11118)

tello.takeoff()
cv2.imwrite("picture.png", frame_read.frame)

tello.land()
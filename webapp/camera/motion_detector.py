import cv2

def detect_motion(prev_gray, frame, threshold=35000):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (21, 21), 0)

    if prev_gray is None:
        return gray, False

    diff = cv2.absdiff(prev_gray, gray)
    _, thresh = cv2.threshold(diff, 80, 255, cv2.THRESH_BINARY)

    motion = thresh.sum() > threshold

    return gray, motion
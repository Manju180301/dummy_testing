import os
import cv2

from ultralytics import YOLO

from .blur_checker import is_blurry
from .face_pose import get_face_pose


FACE_MODEL = YOLO("yolov8n.pt")

TARGET_IMAGES = 15


def process_video(
        video_path,
        emp_id,
        target_images=TARGET_IMAGES
):

    gallery_dir = os.path.join(
        "faces_gallery",
        emp_id
    )

    os.makedirs(
        gallery_dir,
        exist_ok=True
    )

    cap = cv2.VideoCapture(video_path)

    saved_count = 0

    pose_count = {
        "STRAIGHT": 0,
        "LEFT": 0,
        "RIGHT": 0,
        "UP": 0,
        "DOWN": 0
    }

    frame_no = 0

    while cap.isOpened():

        ret, frame = cap.read()

        if not ret:
            break

        frame_no += 1

        if frame_no % 5 != 0:
            continue

        results = FACE_MODEL(
            frame,
            verbose=False
        )

        for result in results:

            for box in result.boxes:

                x1, y1, x2, y2 = map(
                    int,
                    box.xyxy[0]
                )

                face = frame[
                    y1:y2,
                    x1:x2
                ]

                if face.size == 0:
                    continue

                if is_blurry(face):
                    continue

                pose = get_face_pose(face)

                if pose is None:
                    continue
                
                if pose not in pose_count:
                    continue

                if pose_count[pose] >= 3:
                    continue

                pose_count[pose] += 1

                saved_count += 1

                image_path = os.path.join(
                    gallery_dir,
                    f"img_{saved_count}.jpg"
                )

                cv2.imwrite(
                    image_path,
                    face
                )

                print(
                    f"Saved {saved_count} "
                    f"Pose={pose}"
                )

                print(pose_count)

                if all(
                    count >= 3
                    for count in pose_count.values()
                ):

                    cap.release()

                    print(
                        f"{emp_id} completed"
                    )

                    return True

    cap.release()

    return False
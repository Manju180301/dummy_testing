import cv2
import mediapipe as mp

mp_face_mesh = mp.solutions.face_mesh

face_mesh = mp_face_mesh.FaceMesh(
    static_image_mode=True,
    max_num_faces=1,
    refine_landmarks=True
)


def get_face_pose(frame):

    rgb = cv2.cvtColor(
        frame,
        cv2.COLOR_BGR2RGB
    )

    results = face_mesh.process(rgb)

    if not results.multi_face_landmarks:
        return None

    landmarks = results.multi_face_landmarks[0].landmark

    nose = landmarks[1]

    left_cheek = landmarks[234]
    right_cheek = landmarks[454]

    forehead = landmarks[10]
    chin = landmarks[152]

    x_ratio = nose.x - (
        (left_cheek.x + right_cheek.x) / 2
    )

    y_ratio = nose.y - (
        (forehead.y + chin.y) / 2
    )

    if x_ratio < -0.03:
        return "LEFT"

    if x_ratio > 0.03:
        return "RIGHT"

    if y_ratio < -0.03:
        return "UP"

    if y_ratio > 0.03:
        return "DOWN"

    return "STRAIGHT"
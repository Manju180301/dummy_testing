import math

def center(b):
    x1, y1, x2, y2 = b
    return ((x1 + x2) // 2, (y1 + y2) // 2)

def distance(p1, p2):
    return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)


def detect_phone_usage(detections, phone_boxes, threshold=80):
    results = []

    for face in detections:
        fx1, fy1, fx2, fy2 = map(int, face["bbox"])
        fx, fy = (fx1 + fx2) // 2, (fy1 + fy2) // 2

        for phone_bbox in phone_boxes:
            px1, py1, px2, py2 = map(int, phone_bbox)
            px, py = (px1 + px2) // 2, (py1 + py2) // 2

            dist = ((fx - px)**2 + (fy - py)**2) ** 0.5

            if dist < threshold:
                results.append({
                    "person_key": face["person_key"],
                    "distance": round(dist, 2),
                })

    return results

from django.db import models

class FaceRecording(models.Model):
    emp_id = models.CharField(max_length=50,unique=True)
    employee_name = models.CharField(max_length=100,default="Unknown")
    department = models.CharField(max_length=100,default="General")
    video_filename = models.CharField(max_length=255)
    video_path = models.CharField(max_length=500)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "face_recordings"
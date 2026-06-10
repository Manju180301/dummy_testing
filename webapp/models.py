# from django.db import models
# from django.utils import timezone

# class HumanTrack(models.Model):
#     em_id = models.IntegerField(default=0)
#     types = models.CharField(max_length=100, blank=True, null=True)
#     image = models.TextField(blank=True, null=True)
#     body_structure = models.CharField(max_length=200, blank=True, null=True)
#     dress_colour = models.CharField(max_length=200, blank=True, null=True)
#     action = models.CharField(max_length=100, blank=True, null=True)
#     status = models.IntegerField(default=0)
#     remark = models.TextField(blank=True, null=True)
#     created_at = models.DateTimeField(auto_now_add=True)   # or auto_now_add=True
#     updated_at = models.DateTimeField(auto_now=True)

#     class Meta:
#         db_table = "human_track"

from django.db import models

class Employee(models.Model):
    company_id = models.CharField(max_length=50)
    emp_name = models.CharField(max_length=100)
    emp_id = models.CharField(max_length=50)
    emp_type = models.CharField(max_length=50, blank=True, null=True)
    dept = models.CharField(max_length=100, blank=True, null=True)
    designation = models.CharField(max_length=100, blank=True, null=True)
    profile_pic = models.ImageField(upload_to="profile_pic",blank=True,null=True)
    agree_terms = models.BooleanField(default=False)

    STATUS_CHOICES = (
        ("active", "Active"),
        ("inactive", "Inactive"),
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default="active"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "employees"
        unique_together = ("company_id", "emp_id")

        
        
class RecognizedFace(models.Model):
    camera_name = models.CharField(max_length=50)
    emp_id = models.CharField(max_length=50, null=True, blank=True)
    similarity_score = models.FloatField()
    similarity_id = models.CharField(max_length=50, null=True, blank=True)
    image_path = models.CharField(max_length=255)
    phone_detected = models.BooleanField(default=False)
    phone_distance = models.FloatField(null=True, blank=True)
    phone_mail_sent = models.BooleanField(default=False)
    bbox = models.JSONField(null=True, blank=True)
    helmet_detected = models.BooleanField(null=True, blank=True)


    capture_date_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "recognized_faces"
        ordering = ["capture_date_time"]

    

class Rule(models.Model):
    RULE_TYPES = [
        ("meeting", "Meeting Rule"),
        ("allowed_place", "Allowed Place"),
        ("restricted_zone", "Restricted Zone"),
        ("in_out", "In / Out Time Rule"),
        ("group", "Group Gathering"),
        ("phone", "Phone Usage"),
        ("helmet", "Helmet Safety Rule"),
    ]

    rule_type = models.CharField(max_length=30, choices=RULE_TYPES)
    rules_json = models.JSONField(default=dict)   # 🔥 ALL RULES STORED HERE
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.rule_type


class EmailSend(models.Model):
    rule_category = models.CharField(max_length=100, null=True, blank=True)
    employee_id = models.CharField(max_length=50, null=True, blank=True)
    employee_name = models.CharField(max_length=100, null=True, blank=True)
    employee_dept = models.CharField(max_length=100, null=True, blank=True)
    unauthorized_person = models.CharField(max_length=50, null=True, blank=True)
    total_emp = models.IntegerField(null=True, blank=True)
    present_emp = models.IntegerField(null=True, blank=True)
    missing_emp = models.TextField(null=True, blank=True)
    place = models.CharField(max_length=200, null=True, blank=True)
    time = models.CharField(max_length=50, null=True, blank=True)
    allowed_department = models.CharField(max_length=100, null=True, blank=True)
    zone_type = models.CharField(max_length=50, null=True, blank=True)
    person = models.CharField(max_length=50, null=True, blank=True)
    break_type = models.CharField(max_length=100, null=True, blank=True)
    close_count = models.IntegerField(null=True, blank=True)
    detected_count = models.IntegerField(null=True, blank=True)
    known_employee = models.TextField(null=True, blank=True)
    unknown_visitor = models.IntegerField(null=True, blank=True)
    image_path = models.CharField(max_length=255, null=True, blank=True)
     

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "email_send"
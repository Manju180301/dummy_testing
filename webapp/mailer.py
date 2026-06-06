from django.core.mail import EmailMessage
from django.conf import settings
from pathlib import Path
from webapp.models import EmailSend
import platform
import os

def save_email_log(**kwargs):
    EmailSend.objects.create(**kwargs)

def attach_image_if_exists(email, image_path):
    """
    Universal rule to attach image safely.
    Works with:
        ✔ recognized_cctv/...jpg
        ✔ /media/recognized_cctv/...jpg
        ✔ Full absolute path
    """

    if not image_path:
        return

    path_str = str(image_path)

    # If already absolute path
    p = Path(path_str)
    if p.is_absolute() and p.exists():
        email.attach_file(str(p))
        return

    # Remove '/media/' if present
    if path_str.startswith(settings.MEDIA_URL):
        path_str = path_str.replace(settings.MEDIA_URL, "", 1)

    # Convert to filesystem path
    full_path = Path(settings.MEDIA_ROOT) / path_str

    if full_path.exists():
        email.attach_file(str(full_path))

        
#----------------MEETING ALERT-------------------------
def send_meeting_alert(
    to_email,
    place,
    start_time,
    end_time,
    total,
    present,
    missing,
    image_path=None,
):
    subject = "🚨Meeting Attendance Alert"

    body = f"""
Meeting Attendance Alert

Place : {place}
Time  : {start_time} - {end_time}

Total Employees    : {total}
Present Employees  : {present}

Missing Employees:
{", ".join(missing) if missing else "None"}
"""

    email = EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to_email]
    )

    if image_path and Path(image_path).exists():
        email.attach_file(image_path)

    # email.send(fail_silently=True)
    save_email_log(
        rule_category="Meeting Rule",
        place=place,
        total_emp=total,
        present_emp=present,
        missing_emp=", ".join(missing),
        time=f"{start_time}-{end_time}",
        image_path=image_path,
    )


#----------------ALLOWED PLACE ALERT-------------------------
def send_allowed_place_alert(
    to_email,
    emp_id,
    emp_name,
    emp_dept,
    allowed_dept,
    place,
    time_str,
    image_path=None,
    zone_type=None,
    unauthorized_person=None,
):
    subject = "🚨Allowed Place Violation Alert"

    body = f"""
Allowed Place Violation Alert

Zone Type : {zone_type}

Employee  : {emp_id} - {emp_name}
Employee Dept : {emp_dept}

Allowed Department : {allowed_dept}
Place : {place}
Time  : {time_str}

Unauthorized department employee entered restricted place.
"""

    email = EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to_email]
    )

    # attach_image_if_exists(email, image_path)

    # if image_path:
    #     if platform.system() == "Windows":
    #         # Windows logic
    #         if Path(image_path).exists():
    #             email.attach_file(image_path)
    #     else:
    #         # Linux logic
    #         attach_image_if_exists(email, image_path)
    
    if image_path:
        try:
            # remove starting /
            clean_path = image_path.lstrip("/")

            # convert to full path
            full_path = os.path.join(settings.MEDIA_ROOT, clean_path)

            #print("📸 Windows Full Path:", full_path)

            if os.path.exists(full_path):
                email.attach_file(full_path)
            else:
                print("❌ Image not found:", full_path)

        except Exception as e:
            print("❌ Image attach error:", e)

    #email.send(fail_silently=False)
    save_email_log(
        rule_category="Allowed Place Rule",
        place=place,
        employee_id=emp_id,
        employee_name=emp_name,
        employee_dept=emp_dept,
        unauthorized_person=unauthorized_person,
        allowed_department=allowed_dept,
        time=time_str,
        image_path=image_path,
        zone_type=zone_type ,
        
)


#----------------RESTRICTED ZONE ALERT-------------------------
def send_restricted_zone_alert(
    to_email,
    emp_id,
    emp_name,
    emp_dept,
    place,
    time_str,
    image_path=None,
    zone_type=None,
    unauthorized_person=None, #--new
):
    subject = "🚨Restricted Zone Violation Alert"

    body = f"""
Restricted Zone Alert
Zone Type : {zone_type.upper()}

Employee : {emp_id} - {emp_name}
Department : {emp_dept}
Place : {place}
Time : {time_str}

Unauthorized entry detected.
"""

    email = EmailMessage(
        subject,
        body,
        settings.DEFAULT_FROM_EMAIL,
        [to_email]
    )


    #attach_image_if_exists(email, image_path)

    # if image_path:
    #     if platform.system() == "Windows":
    #         # Windows logic
    #         if Path(image_path).exists():
    #             email.attach_file(image_path)
    #     else:
    #         # Linux logic
    #         attach_image_if_exists(email, image_path)
    
    if image_path:
        try:
            clean_path = image_path.lstrip("/")

            # convert to full path
            full_path = os.path.join(settings.MEDIA_ROOT, clean_path)
            if os.path.exists(full_path):
                email.attach_file(full_path)
            else:
                print("❌ Image not found:", full_path)

        except Exception as e:
            print("❌ Image attach error:", e)

    #email.send(fail_silently=False)
    save_email_log(
    rule_category="Restricted Zone Rule",
    place=place,
    employee_id=emp_id,
    employee_name=emp_name,
    employee_dept=emp_dept,
    unauthorized_person=unauthorized_person,
    zone_type=zone_type,
    time=time_str,
    image_path=image_path
)

# ----------- IN / OUT TIME ALERT MAIL -------------
def send_inout_time_alert(
    to_email,
    employee,
    violation_type,
    violation_time,
    image_path=None,
    place=None
):
    subject = f"🚨In/Out Time Alert - {violation_type}"

    body = f"""
In / Out Time Rule Alert

Violation Type : {violation_type}

Employee ID    : {employee.emp_id}
Employee Name  : {employee.emp_name}
Department     : {employee.dept}

Time           : {violation_time}

Please take necessary action.
"""

    email = EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to_email]
    )


    # attach_image_if_exists(email, image_path)

    if image_path:
        if platform.system() == "Windows":
            # Windows logic
            if Path(image_path).exists():
                email.attach_file(image_path)
        else:
            # Linux logic
            attach_image_if_exists(email, image_path)

    # email.send(fail_silently=False)
    save_email_log(
    rule_category="InOut Rule",
    place=place,
    employee_id=employee.emp_id,
    employee_name=employee.emp_name,
    employee_dept=employee.dept,
    break_type=violation_type,
    time=violation_time,
    image_path=image_path
)

#--------------------UNKNOW PERSON ALERT--------------
def send_unknown_alert(
    to_email,
    camera_name,
    time_str,
    image_path=None
):
    subject = "🚨 Unknown Person Detected"

    body = f"""
Unknown Person Alert

Person        : UNKNOWN
Camera        : {camera_name}
Time          : {time_str}

Please verify immediately.
"""

    email = EmailMessage(
        subject,
        body,
        settings.DEFAULT_FROM_EMAIL,
        [to_email]
    )

    
    # attach_image_if_exists(email, image_path)

    if image_path:
        if platform.system() == "Windows":
            # Windows logic
            if Path(image_path).exists():
                email.attach_file(image_path)
        else:
            # Linux logic
            attach_image_if_exists(email, image_path)

    #email.send(fail_silently=False)
    save_email_log(
        rule_category="Unknown Person",
        place=camera_name,
        time=time_str,
        image_path=image_path,
        person="UNKNOWN"
)


#--------------------PHONE USAGE ALERT--------------
def send_phone_usage_alert(to_email, emp, place, time_str, image_path):
    subject = "📵 Phone Usage Alert"

    body = f"""
Phone Usage Detected

Employee : {emp.emp_id} - {emp.emp_name}
Department : {emp.dept}

Place : {place}
Time  : {time_str}

Phone usage detected during working hours.
"""

    email = EmailMessage(
        subject,
        body,
        settings.DEFAULT_FROM_EMAIL,
        [to_email]
    )

    # attach_image_if_exists(email, image_path)

    if image_path:
        if platform.system() == "Windows":
            # Windows logic
            if Path(image_path).exists():
                email.attach_file(image_path)
        else:
            # Linux logic
            attach_image_if_exists(email, image_path)

    #email.send(fail_silently=False)
    save_email_log(
        rule_category="Phone Usage Rule",
        place=place,
        employee_id=emp.emp_id,
        employee_name=emp.emp_name,
        employee_dept=emp.dept,
        time=time_str,
        image_path=image_path
    )

#-----------------SAFETY RULE---------------------
def send_helmet_alert(
    to_email,
    place,
    time_str,
    emp=None,
    image_path=None
):
    subject = "🚨 Helmet Safety Violation Alert"

    if emp:
        emp_info = f"""
Employee ID   : {emp.emp_id}
Employee Name : {emp.emp_name}
Department    : {emp.dept}
"""
    else:
        emp_info = "Person : UNKNOWN / VISITOR\n"

    body = f"""
Helmet Safety Violation Detected

{emp_info}
Place : {place}
Violation : Helmet NOT worn
Time : {time_str}

⚠️ This is a safety-critical violation.
Please take immediate action.
"""

    email = EmailMessage(
        subject,
        body,
        settings.DEFAULT_FROM_EMAIL,
        [to_email]
    )

    # attach_image_if_exists(email, image_path)

    if image_path:
        if platform.system() == "Windows":
            # Windows logic
            if Path(image_path).exists():
                email.attach_file(image_path)
        else:
            # Linux logic
            attach_image_if_exists(email, image_path)

    #email.send(fail_silently=False)
    save_email_log(
        rule_category="Helmet Rule",
        place=place,
        employee_id=emp.emp_id if emp else None,
        employee_name=emp.emp_name if emp else None,
        employee_dept=emp.dept if emp else None,
        person="UNKNOWN" if not emp else None,
        time=time_str,
        image_path=image_path
)
    
#-----------------No Employee  RULE---------------------
from .models import NoEmployeeShift
def get_shift_name(alert_time):

    shifts = NoEmployeeShift.objects.all()

    current_time = alert_time.time()

    for shift in shifts:

        if shift.start_time <= current_time <= shift.end_time:
            return shift.shift_name

    return "Unknown Shift"

def send_no_employee_alert(to_email, place, count, start_time, end_time, image_path=None, time_range=None):
    
    shift_name = get_shift_name(start_time)
    duration_seconds = int((end_time - start_time).total_seconds())
    duration_minutes = duration_seconds // 60
    duration_seconds_rem = duration_seconds % 60
    
    if duration_minutes > 0:
        duration_text = f"{duration_minutes} minute(s)"
    else:
        duration_text = f"{duration_seconds_rem} seconds"

    subject = "🚨 No Employee Detected Alert"
    
    body = f"""
No Employee Detected

Place : {place}
Shift : {shift_name}

No employees were detected for {duration_text} continuously.

Time Period:
From : {start_time.strftime("%H:%M:%S")}
To   : {end_time.strftime("%H:%M:%S")}

Detected Count : {count}

⚠️ Please verify the workplace immediately.
"""

    email = EmailMessage(
        subject,
        body,
        settings.DEFAULT_FROM_EMAIL,
        [to_email]
    )

    if image_path:
        try:
            if Path(image_path).exists():
                email.attach_file(image_path)
            else:
                print(f"❌ Image not found: {image_path}")
        except Exception as e:
            print(f"❌ Image attach error: {e}")

    
    #email.send(fail_silently=False)
    
    save_email_log(
        rule_category="No Employee Rule",
        place=place,
        detected_count=count,
        time=time_range,  
        image_path=image_path,
        shift_name=shift_name,
    )
    

#-----------------group Detection RULE---------------------
def send_group_alert(to_email, place, count, start_time, end_time, image_path=None, extra_body=""):
    duration = int((end_time - start_time).total_seconds() // 60)

    subject = "🚨 Group Detection Alert"

    body = f"""
Group Detected

Place : {place}

{count} people stayed together for {duration} minute(s)

From : {start_time.strftime("%H:%M:%S")}
To   : {end_time.strftime("%H:%M:%S")}
"""

    email = EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL, [to_email])

    if image_path and Path(image_path).exists():
        email.attach_file(image_path)

    #email.send(fail_silently=False)

    save_email_log(
        rule_category="Group Rule",
        place=place,
        detected_count=count,
        time=f"{start_time.strftime('%Y-%m-%d %H:%M')} - {end_time.strftime('%H:%M')}",
        image_path=image_path
    )
    

# ================= WORK DETECTION ALERT MAIL =================

def send_work_alert(to_email, place, minutes_worked, required_minutes, start_time, end_time, image_path=None, message=""):
    subject = "🚨 Work Attendance Alert"
    
    body = f"""
Work Attendance Alert

Location: {place}

{message}

Details:
- Work Period: {start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}
- Detected Work Duration: {minutes_worked} minutes
- Required Minimum: {required_minutes} minutes

Please verify the workplace immediately.
"""
    
    email = EmailMessage(
        subject,
        body,
        settings.DEFAULT_FROM_EMAIL,
        [to_email]
    )
    
    if image_path:
        if Path(image_path).exists():
            email.attach_file(image_path)
    
    
    #email.send(fail_silently=False)
        
    EmailSend.objects.create(
        rule_category="Work Rule",
        place=place,
        detected_count=minutes_worked,
        total_emp=required_minutes,
        time=f"{start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}",
        image_path=image_path,
        missing_emp=message
    )
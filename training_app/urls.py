from django.urls import path
from . import views

urlpatterns = [

    path('', views.enter_emp_id, name='enter_emp_id'),
    path('face-record/',views.face_record,name='face_record'),
    path('upload-video/',views.upload_face_video,name='upload_face_video'),
    path('training-dashboard/',views.training_dashboard,name='training_dashboard'),
    path('start-training/',views.start_training,name='start_training'),
    path('upload-images/',views.upload_images,name='upload_images'),
    path('retrain/<str:emp_id>/',views.retrain_employee,name='retrain_employee'),
    path('retrain-all/',views.retrain_all,name='retrain_all'),
    path("delete/<str:emp_id>/",views.delete_employee,name="delete_employee"),
    path("retrain-selected/",views.retrain_selected,name="retrain_selected"),

]
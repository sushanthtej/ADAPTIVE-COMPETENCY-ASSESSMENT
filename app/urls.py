from django.urls import path
from .views import *

urlpatterns = [
    path('', index, name='index'),
    path('user_login/', user_login, name='user_login'),
    path('user_signup/', user_signup, name='user_signup'),
    path('dashboard/', dashboard, name='dashboard'),
    path('user_logout/', user_logout, name='user_logout'),
    path('view_categories/', view_categories, name='view_categories'),
    path('test/<str:topic>/<str:difficulty>/', test_conduct, name='test_conduct'),
    path('test_complete/', test_complete, name='test_complete'),
    path('save_answer/', save_answer, name='save_answer'),
    path('test_ready_to_submit/<str:topic>/<str:difficulty>/', test_ready_to_submit, name='test_ready_to_submit'),
    path('submit_test/', submit_test, name='submit_test'),
    path('auto_submit_test/', auto_submit_test, name='auto_submit_test'),
    path('exit_test/', exit_test, name='exit_test'),
    path('skip_question/', skip_question, name='skip_question'),
    path('test_history/', view_test_history, name='test_history'),
    path('test_detail/<uuid:assessment_id>/', view_test_detail, name='test_detail'),
    path('leaderboard/', leaderboard, name='leaderboard'),
]

from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("trigger-drought/", views.trigger_drought, name="trigger_drought"),
    path("farmers/", views.farmers_list, name="farmers_list"),
    path("loans/", views.loans_list, name="loans_list"),
    path("api/request-loan/", views.request_loan, name="request_loan"),
    path("simulate-loan/", views.simulate_loan, name="simulate_loan"),
    path("reset-fund/", views.reset_fund, name="reset_fund"),
    path("reset-drought/", views.reset_drought, name="reset_drought"),
    # Oracle simulation endpoints
    path("api/rainfall/", views.rainfall_data, name="rainfall_data"),
    path("api/oracle-trigger/", views.oracle_trigger, name="oracle_trigger"),
]

from django.contrib import admin
from .models import MFI, Farmer, LoanProduct, LoanFund, Loan, ClimateTrigger


@admin.register(MFI)
class MFIAdmin(admin.ModelAdmin):
    list_display = ("name", "country")
    search_fields = ("name", "country")


@admin.register(Farmer)
class FarmerAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "national_id", "location", "qualification_status", "mfi")
    list_filter = ("qualification_status", "mfi")
    search_fields = ("name", "national_id", "phone", "location")
    list_editable = ("qualification_status",)


@admin.register(LoanProduct)
class LoanProductAdmin(admin.ModelAdmin):
    list_display = ("name", "amount", "term_months", "grace_period_months", "mfi")
    list_filter = ("mfi",)


@admin.register(LoanFund)
class LoanFundAdmin(admin.ModelAdmin):
    list_display = ("name", "funding_source", "total_capital", "available_capital", "utilization_pct")
    readonly_fields = ("utilization_pct",)

    def utilization_pct(self, obj):
        return f"{obj.utilization_pct}%"
    utilization_pct.short_description = "Utilization %"


@admin.register(Loan)
class LoanAdmin(admin.ModelAdmin):
    list_display = ("id", "farmer", "loan_product", "amount", "status", "triggered", "start_date", "end_date")
    list_filter = ("status", "triggered", "loan_product", "loan_fund")
    search_fields = ("farmer__name", "farmer__national_id")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"


@admin.register(ClimateTrigger)
class ClimateTriggerAdmin(admin.ModelAdmin):
    list_display = ("region", "rainfall", "threshold", "drought", "triggered_at")
    list_filter = ("drought", "region")
    readonly_fields = ("triggered_at",)
    date_hierarchy = "triggered_at"

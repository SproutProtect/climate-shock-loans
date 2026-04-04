from django.db import models
from django.utils import timezone
import datetime


class MFI(models.Model):
    name = models.CharField(max_length=255)
    country = models.CharField(max_length=100)

    class Meta:
        verbose_name = "MFI"
        verbose_name_plural = "MFIs"

    def __str__(self):
        return f"{self.name} ({self.country})"


class Farmer(models.Model):
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=30)
    national_id = models.CharField(max_length=50, unique=True)
    bank_id = models.CharField(max_length=50)
    location = models.CharField(max_length=255)
    qualification_status = models.BooleanField(default=False)
    mfi = models.ForeignKey(MFI, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        qualified = "✓" if self.qualification_status else "✗"
        return f"{self.name} [{qualified}]"


class LoanProduct(models.Model):
    name = models.CharField(max_length=255)
    amount = models.FloatField(help_text="Loan amount in USD")
    term_months = models.IntegerField(default=12)
    grace_period_months = models.IntegerField(default=3)
    mfi = models.ForeignKey(MFI, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.name} (${self.amount:,.0f})"


class LoanFund(models.Model):
    name = models.CharField(max_length=255)
    total_capital = models.IntegerField(default=100000, help_text="Total fund capital in USD")
    available_capital = models.IntegerField(default=100000, help_text="Remaining available capital in USD")
    loans_issued = models.IntegerField(default=0, help_text="Number of loans disbursed from this fund")
    funding_source = models.CharField(max_length=255, help_text="e.g. WFP, Government")
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} (${self.available_capital:,} available)"

    @property
    def utilization_pct(self):
        if self.total_capital == 0:
            return 0
        used = self.total_capital - self.available_capital
        return round((used / self.total_capital) * 100, 1)

    def withdraw(self, amount):
        """Deduct amount from available capital and increment loans_issued. Returns True if successful."""
        amount = int(amount)
        if self.available_capital >= amount:
            self.available_capital -= amount
            self.loans_issued += 1
            self.save()
            return True
        return False


class Loan(models.Model):
    STATUS_PENDING = "pending"
    STATUS_AVAILABLE = "available"
    STATUS_DISBURSED = "disbursed"
    STATUS_REPAID = "repaid"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_AVAILABLE, "Available"),
        (STATUS_DISBURSED, "Disbursed"),
        (STATUS_REPAID, "Repaid"),
    ]

    farmer = models.ForeignKey(Farmer, on_delete=models.CASCADE, related_name="loans")
    loan_product = models.ForeignKey(LoanProduct, on_delete=models.CASCADE)
    loan_fund = models.ForeignKey(LoanFund, on_delete=models.SET_NULL, null=True, blank=True)
    amount = models.FloatField(help_text="Disbursed loan amount in USD")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    triggered = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Loan #{self.pk} — {self.farmer.name} ({self.status})"


class ClimateTrigger(models.Model):
    region = models.CharField(max_length=255)
    rainfall = models.FloatField(help_text="Measured rainfall in mm")
    threshold = models.FloatField(help_text="Drought threshold in mm")
    drought = models.BooleanField(default=False)
    triggered_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-triggered_at"]

    def __str__(self):
        status = "DROUGHT" if self.drought else "Normal"
        ts = self.triggered_at.strftime("%Y-%m-%d %H:%M")
        return f"{self.region} — {status} @ {ts}"

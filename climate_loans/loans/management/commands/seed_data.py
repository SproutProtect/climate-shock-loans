"""
Management command: python manage.py seed_data

Creates realistic sample data for the Climate Shock Loans hackathon prototype.
Safe to run multiple times — skips existing records.
"""
from django.core.management.base import BaseCommand
from loans.models import MFI, Farmer, LoanProduct, LoanFund, Loan


FARMERS = [
    ("Abebe Girma",    "+251-911-111-001", "ETH-001", "BNK-001", "Tigray, Adwa"),
    ("Tigist Haile",   "+251-911-111-002", "ETH-002", "BNK-002", "Tigray, Axum"),
    ("Mulugeta Tesfaye","+251-911-111-003","ETH-003", "BNK-003", "Tigray, Mekelle"),
    ("Selamawit Bekele","+251-911-111-004","ETH-004", "BNK-004", "Tigray, Shire"),
    ("Yonas Alemu",    "+251-911-111-005", "ETH-005", "BNK-005", "Tigray, Adwa"),
    ("Hiwot Tadesse",  "+251-911-111-006", "ETH-006", "BNK-006", "Tigray, Axum"),
    ("Getachew Maru",  "+251-911-111-007", "ETH-007", "BNK-007", "Amhara, Bahir Dar"),
    ("Almaz Worku",    "+251-911-111-008", "ETH-008", "BNK-008", "Amhara, Gondar"),
]


class Command(BaseCommand):
    help = "Seeds the database with sample climate loan data"

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Seeding Climate Shock Loans data…"))

        # MFI
        mfi, created = MFI.objects.get_or_create(
            name="Amhara Credit & Savings",
            defaults={"country": "Ethiopia"},
        )
        if created:
            self.stdout.write(f"  Created MFI: {mfi}")

        # Loan Product
        product, created = LoanProduct.objects.get_or_create(
            name="Drought Emergency Loan",
            defaults={
                "amount": 500.0,
                "term_months": 12,
                "grace_period_months": 3,
                "mfi": mfi,
            },
        )
        if created:
            self.stdout.write(f"  Created LoanProduct: {product}")

        # Loan Fund
        fund, created = LoanFund.objects.get_or_create(
            name="WFP Climate Resilience Fund 2026",
            defaults={
                "total_capital": 100_000.0,
                "available_capital": 100_000.0,
                "funding_source": "World Food Programme",
            },
        )
        if created:
            self.stdout.write(f"  Created LoanFund: {fund}")

        # Farmers & Loans
        farmers_created = 0
        loans_created = 0
        for i, (name, phone, nid, bid, loc) in enumerate(FARMERS):
            farmer, created = Farmer.objects.get_or_create(
                national_id=nid,
                defaults={
                    "name": name,
                    "phone": phone,
                    "bank_id": bid,
                    "location": loc,
                    "qualification_status": True,
                    "mfi": mfi,
                },
            )
            if created:
                farmers_created += 1

            _, loan_created = Loan.objects.get_or_create(
                farmer=farmer,
                loan_product=product,
                defaults={
                    "amount": product.amount,
                    "status": Loan.STATUS_PENDING,
                    "triggered": False,
                },
            )
            if loan_created:
                loans_created += 1

        self.stdout.write(f"  Farmers created: {farmers_created} (skipped {len(FARMERS) - farmers_created} existing)")
        self.stdout.write(f"  Loans created:   {loans_created}")
        self.stdout.write(self.style.SUCCESS(
            "\nDone! Visit http://127.0.0.1:4000/ for the dashboard.\n"
            "Trigger drought: GET http://127.0.0.1:4000/trigger-drought/?region=Tigray&rainfall=10&threshold=30"
        ))

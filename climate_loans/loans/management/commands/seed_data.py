"""
Management command: python manage.py seed_data

Creates realistic sample data for the Climate Shock Loans hackathon prototype.
Safe to run multiple times — skips existing records.

Generates 1,000 Ethiopian farmers across multiple regions, each with a
pending loan between $55 and $120.
"""
import random
from django.core.management.base import BaseCommand
from loans.models import MFI, Farmer, LoanProduct, LoanFund, Loan

FIRST_NAMES = [
    "Abebe", "Tigist", "Mulugeta", "Selamawit", "Yonas", "Hiwot", "Getachew",
    "Almaz", "Dawit", "Mekdes", "Biruk", "Selam", "Tesfaye", "Asmera", "Kidan",
    "Robel", "Tsehay", "Hagos", "Miriam", "Solomon", "Feven", "Berhe", "Liya",
    "Amanuel", "Rahel", "Tekle", "Senait", "Kibrom", "Elsa", "Habtom",
]

LAST_NAMES = [
    "Girma", "Haile", "Tesfaye", "Bekele", "Alemu", "Tadesse", "Maru", "Worku",
    "Kebede", "Desta", "Mekonnen", "Gebre", "Wolde", "Teka", "Araya", "Tsegay",
    "Berhane", "Hadgu", "Negash", "Gebru", "Abraha", "Kiros", "Girmay", "Teklu",
    "Berhe", "Seyum", "Weldu", "Fisseha", "Gerezgiher", "Habtezion",
]

LOCATIONS = [
    "Tigray, Adwa", "Tigray, Axum", "Tigray, Mekelle", "Tigray, Shire",
    "Tigray, Adigrat", "Tigray, Wukro", "Tigray, Maychew", "Tigray, Alamata",
    "Amhara, Bahir Dar", "Amhara, Gondar", "Amhara, Dessie", "Amhara, Debre Markos",
    "Amhara, Woldia", "Amhara, Debre Birhan", "Oromia, Jimma", "Oromia, Adama",
    "Oromia, Bishoftu", "Oromia, Nekemte", "SNNPR, Hawassa", "SNNPR, Arba Minch",
    "Afar, Semera", "Somali, Jigjiga", "Benishangul, Assosa",
]

TOTAL_FARMERS = 1_000


class Command(BaseCommand):
    help = "Seeds the database with 1,000 sample farmers and random loan amounts ($55–$120)"

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Seeding Climate Shock Loans data…"))

        # MFI
        mfi, created = MFI.objects.get_or_create(
            name="Amhara Credit & Savings",
            defaults={"country": "Ethiopia"},
        )
        if created:
            self.stdout.write(f"  Created MFI: {mfi}")

        # Loan Product — amount is the ceiling; actual per-loan amount varies
        product, created = LoanProduct.objects.get_or_create(
            name="Drought Emergency Loan",
            defaults={
                "amount": 120.0,
                "term_months": 12,
                "grace_period_months": 3,
                "mfi": mfi,
            },
        )
        if created:
            self.stdout.write(f"  Created LoanProduct: {product}")

        # Loan Fund — $120,000 covers 1,000 farmers at up to $120 each
        fund, created = LoanFund.objects.get_or_create(
            name="WFP Climate Resilience Fund 2026",
            defaults={
                "total_capital": 120_000.0,
                "available_capital": 120_000.0,
                "funding_source": "World Food Programme",
            },
        )
        if created:
            self.stdout.write(f"  Created LoanFund: {fund}")

        # Farmers & Loans
        farmers_created = 0
        loans_created = 0

        for i in range(1, TOTAL_FARMERS + 1):
            first = random.choice(FIRST_NAMES)
            last  = random.choice(LAST_NAMES)
            name  = f"{first} {last}"
            nid   = f"ETH-{i:04d}"
            bid   = f"BNK-{i:04d}"
            phone = f"+251-9{random.randint(10,99)}-{random.randint(100,999)}-{i:03d}"
            loc   = random.choice(LOCATIONS)
            amount = random.randint(55, 120)

            farmer, f_created = Farmer.objects.get_or_create(
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
            if f_created:
                farmers_created += 1

            _, l_created = Loan.objects.get_or_create(
                farmer=farmer,
                loan_product=product,
                defaults={
                    "amount": amount,
                    "status": Loan.STATUS_PENDING,
                    "loan_fund": fund,
                    "triggered": False,
                },
            )
            if l_created:
                loans_created += 1

            if i % 100 == 0:
                self.stdout.write(f"  … {i}/{TOTAL_FARMERS} processed")

        self.stdout.write(f"  Farmers created: {farmers_created} (skipped {TOTAL_FARMERS - farmers_created} existing)")
        self.stdout.write(f"  Loans created:   {loans_created}")
        self.stdout.write(self.style.SUCCESS(
            "\nDone! Visit the dashboard to see 1,000 farmers ready for drought disbursement.\n"
        ))

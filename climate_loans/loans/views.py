import json
import random
import datetime
import logging
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.shortcuts import render
from django.utils import timezone

from .models import Farmer, Loan, LoanFund, ClimateTrigger, LoanProduct

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def dashboard(request):
    latest_trigger = ClimateTrigger.objects.first()
    drought_active = latest_trigger.drought if latest_trigger else False

    total_farmers = Farmer.objects.count()
    qualified_farmers = Farmer.objects.filter(qualification_status=True).count()

    loans_by_status = {
        "pending": Loan.objects.filter(status=Loan.STATUS_PENDING).count(),
        "available": Loan.objects.filter(status=Loan.STATUS_AVAILABLE).count(),
        "disbursed": Loan.objects.filter(status=Loan.STATUS_DISBURSED).count(),
        "repaid": Loan.objects.filter(status=Loan.STATUS_REPAID).count(),
    }
    total_loans = sum(loans_by_status.values())

    funds = LoanFund.objects.all()
    loan_fund = LoanFund.objects.first()
    recent_triggers = ClimateTrigger.objects.all()[:10]
    recent_loans = Loan.objects.select_related("farmer", "loan_product").order_by("-created_at")[:20]

    context = {
        "drought_active": drought_active,
        "latest_trigger": latest_trigger,
        "total_farmers": total_farmers,
        "qualified_farmers": qualified_farmers,
        "loans_by_status": loans_by_status,
        "total_loans": total_loans,
        "funds": funds,
        "loan_fund": loan_fund,
        "recent_triggers": recent_triggers,
        "recent_loans": recent_loans,
    }
    return render(request, "loans/dashboard.html", context)


# ---------------------------------------------------------------------------
# Core logic: activate loans when drought is detected
# ---------------------------------------------------------------------------

def activate_loans_due_to_drought():
    """
    Find all pending loans belonging to pre-qualified farmers and mark them
    as available, deducting amounts from the first fund that has capital.

    Returns a list of dicts describing each activated loan.
    """
    pending_loans = Loan.objects.filter(
        status=Loan.STATUS_PENDING,
        farmer__qualification_status=True,
    ).select_related("farmer", "loan_product", "loan_fund")

    fund = LoanFund.objects.filter(available_capital__gt=0).first()
    today = datetime.date.today()
    activated_loans = []

    for loan in pending_loans:
        if fund and fund.available_capital >= loan.amount:
            fund.available_capital -= loan.amount
            loan.status = Loan.STATUS_AVAILABLE
            loan.triggered = True
            loan.start_date = today
            loan.end_date = today + datetime.timedelta(days=365)
            loan.loan_fund = fund
            loan.save()
            activated_loans.append({
                "loan_id": loan.pk,
                "farmer": loan.farmer.name,
                "amount": loan.amount,
            })
            logger.info("Loan #%s activated for farmer %s ($%.2f)", loan.pk, loan.farmer.name, loan.amount)

    if fund and activated_loans:
        fund.save()
        logger.info("LoanFund '%s' updated — remaining capital: $%.2f", fund.name, fund.available_capital)

    return activated_loans


# ---------------------------------------------------------------------------
# API: Trigger Drought (manual / parameterised)
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["POST", "GET"])
def trigger_drought(request):
    """
    Simulate a climate trigger event.

    POST body (JSON):
        {
            "region": "Tigray",
            "rainfall": 12.5,
            "threshold": 30.0
        }

    GET (for quick testing): uses defaults — drought = True.
    """
    if request.method == "GET":
        region = request.GET.get("region", "Default Region")
        rainfall = float(request.GET.get("rainfall", 10.0))
        threshold = float(request.GET.get("threshold", 30.0))
    else:
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON body"}, status=400)
        region = body.get("region", "Default Region")
        rainfall = float(body.get("rainfall", 10.0))
        threshold = float(body.get("threshold", 30.0))

    is_drought = rainfall < threshold

    trigger = ClimateTrigger.objects.create(
        region=region,
        rainfall=rainfall,
        threshold=threshold,
        drought=is_drought,
        triggered_at=timezone.now(),
    )

    logger.info("Climate trigger created — region: %s, rainfall: %.1f mm, drought: %s", region, rainfall, is_drought)

    activated_loans = []
    if is_drought:
        activated_loans = activate_loans_due_to_drought()

    return JsonResponse({
        "trigger_id": trigger.pk,
        "region": region,
        "rainfall_mm": rainfall,
        "threshold_mm": threshold,
        "drought": is_drought,
        "triggered_at": trigger.triggered_at.isoformat(),
        "loans_activated": len(activated_loans),
        "activated_loans": activated_loans,
        "message": (
            f"Drought detected — {len(activated_loans)} loans activated."
            if is_drought else
            "No drought condition. No loans activated."
        ),
    })


# ---------------------------------------------------------------------------
# Fake CHIRPS data generator
# ---------------------------------------------------------------------------

# Regions modelled on real CHIRPS coverage zones (lat/lon bounding boxes)
CHIRPS_REGIONS = [
    {"name": "Tigray, Ethiopia",    "lat": 14.1,  "lon": 38.7},
    {"name": "Sahel, Niger",        "lat": 14.8,  "lon":  8.0},
    {"name": "Somali, Ethiopia",    "lat":  6.9,  "lon": 44.5},
    {"name": "Karamoja, Uganda",    "lat":  3.1,  "lon": 34.5},
    {"name": "Turkana, Kenya",      "lat":  3.5,  "lon": 36.0},
]

# Drought threshold in mm (typical CHIRPS pentadal / monthly threshold)
CHIRPS_DROUGHT_THRESHOLD_MM = 30.0


def _fake_chirps_reading():
    """
    Simulate a CHIRPS pentadal (5-day) rainfall reading.

    CHIRPS reports rainfall in mm over a 5-day window.
    In drought years the Sahel / Horn of Africa typically sees
    0–15 mm; normal seasons see 30–80 mm.

    We bias toward drought (60 % chance) so demos reliably trigger loans.
    """
    region = random.choice(CHIRPS_REGIONS)

    if random.random() < 0.6:
        # Drought scenario: very low rainfall
        rainfall = round(random.uniform(0.0, 14.9), 2)
    else:
        # Normal / wet scenario
        rainfall = round(random.uniform(30.0, 85.0), 2)

    return {
        "source": "CHIRPS v2.0 (simulated)",
        "region": region["name"],
        "latitude": region["lat"],
        "longitude": region["lon"],
        "period": "pentadal (5-day)",
        "date": datetime.date.today().isoformat(),
        "rainfall_mm": rainfall,
        "threshold_mm": CHIRPS_DROUGHT_THRESHOLD_MM,
        "drought": rainfall < CHIRPS_DROUGHT_THRESHOLD_MM,
    }


# ---------------------------------------------------------------------------
# API: Rainfall data (oracle data source)
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["GET"])
def rainfall_data(request):
    """
    Returns a simulated CHIRPS pentadal rainfall reading.

    The response mimics the structure of a real CHIRPS data feed.
    In production, replace _fake_chirps_reading() with a live call to
    the CHIRPS FTP/API or NASA POWER.
    """
    data = _fake_chirps_reading()

    logger.info(
        "[CHIRPS] region=%s  rainfall=%.2f mm  threshold=%.1f mm  drought=%s",
        data["region"], data["rainfall_mm"], data["threshold_mm"], data["drought"],
    )

    # oracle_simulation.py expects top-level "rainfall", "threshold", "drought"
    return JsonResponse({
        **data,
        "rainfall": data["rainfall_mm"],
        "threshold": data["threshold_mm"],
    })


# ---------------------------------------------------------------------------
# API: Oracle trigger (called by the oracle simulation script)
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["GET"])
def oracle_trigger(request):
    """
    Entry point for the external oracle simulation script.
    Activates loans when drought conditions are confirmed.
    """
    logger.info("Oracle trigger received — activating loans due to drought")

    activated_loans = activate_loans_due_to_drought()

    logger.info("Oracle trigger complete — %d loan(s) activated", len(activated_loans))

    return JsonResponse({
        "status": "success",
        "loans_activated": len(activated_loans),
        "activated_loans": activated_loans,
        "message": f"Oracle trigger executed — {len(activated_loans)} loan(s) activated.",
    })


# ---------------------------------------------------------------------------
# API: Simulate Loan (server-side amount generation + fund withdrawal)
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["POST", "GET"])
def simulate_loan(request):
    """
    End-to-end loan simulation endpoint.

    1. Generates a random loan amount ($55–$120) server-side.
    2. Checks drought is active (contract pre-condition).
    3. Calls fund.withdraw(amount) — mirrors contract.requestLoan(amount).
    4. Returns loan_amount, status, updated capital, and loans_issued count.

    In production, step 3 becomes a signed web3 transaction.
    """
    latest_trigger = ClimateTrigger.objects.first()
    drought_active = latest_trigger.drought if latest_trigger else False

    amount = random.randint(55, 120)
    fund = LoanFund.objects.first()

    if not drought_active:
        return JsonResponse({
            "loan_amount": amount,
            "status": "rejected",
            "reason": "No active drought — contract condition not met",
            "available_capital": fund.available_capital if fund else 0,
            "loans_issued": fund.loans_issued if fund else 0,
        })

    if not fund:
        return JsonResponse({
            "loan_amount": amount,
            "status": "rejected",
            "reason": "No loan fund configured",
            "available_capital": 0,
            "loans_issued": 0,
        })

    approved = fund.withdraw(amount)

    logger.info(
        "simulate_loan — amount=$%d drought=%s approved=%s remaining=$%d",
        amount, drought_active, approved, fund.available_capital,
    )

    return JsonResponse({
        "loan_amount": amount,
        "status": "approved" if approved else "rejected",
        "reason": None if approved else "insufficient reserves",
        "available_capital": fund.available_capital,
        "loans_issued": fund.loans_issued,
        "last_updated": fund.last_updated.isoformat(),
    })


# ---------------------------------------------------------------------------
# API: Request Loan (simulation layer → mirrors contract.requestLoan)
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["POST"])
def request_loan(request):
    """
    Simulates contract.requestLoan(amount).

    POST body (JSON): { "amount": 85 }

    Checks the primary fund for sufficient capital and deducts if approved.
    In production, replace the fund.withdraw() call with a signed web3
    transaction to the on-chain contract.
    """
    try:
        body = json.loads(request.body)
        amount = int(body.get("amount", 0))
    except (json.JSONDecodeError, ValueError, TypeError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    if amount <= 0:
        return JsonResponse({"error": "Amount must be a positive integer"}, status=400)

    fund = LoanFund.objects.filter(available_capital__gt=0).first()

    if not fund:
        return JsonResponse({
            "approved": False,
            "reason": "No active loan fund",
            "available_capital": 0,
        })

    approved = fund.withdraw(amount)

    if approved:
        logger.info("Loan request approved — $%d withdrawn from fund '%s' (remaining: $%d)",
                    amount, fund.name, fund.available_capital)
        return JsonResponse({
            "approved": True,
            "amount": amount,
            "fund": fund.name,
            "available_capital": fund.available_capital,
            "last_updated": fund.last_updated.isoformat(),
        })
    else:
        logger.info("Loan request rejected — insufficient reserves (requested $%d, available $%d)",
                    amount, fund.available_capital)
        return JsonResponse({
            "approved": False,
            "reason": "insufficient reserves",
            "available_capital": fund.available_capital,
        })


# ---------------------------------------------------------------------------
# API: Farmers
# ---------------------------------------------------------------------------

def farmers_list(request):
    farmers = Farmer.objects.select_related("mfi").all().values(
        "id", "name", "phone", "national_id", "bank_id",
        "location", "qualification_status", "mfi__name",
    )
    data = [
        {
            "id": f["id"],
            "name": f["name"],
            "phone": f["phone"],
            "national_id": f["national_id"],
            "bank_id": f["bank_id"],
            "location": f["location"],
            "qualified": f["qualification_status"],
            "mfi": f["mfi__name"],
        }
        for f in farmers
    ]
    return JsonResponse({"count": len(data), "farmers": data})


# ---------------------------------------------------------------------------
# API: Loans
# ---------------------------------------------------------------------------

def loans_list(request):
    status_filter = request.GET.get("status")
    qs = Loan.objects.select_related("farmer", "loan_product", "loan_fund")
    if status_filter:
        qs = qs.filter(status=status_filter)

    data = [
        {
            "id": loan.pk,
            "farmer": loan.farmer.name,
            "farmer_id": loan.farmer.pk,
            "loan_product": loan.loan_product.name,
            "amount": loan.amount,
            "status": loan.status,
            "triggered": loan.triggered,
            "start_date": loan.start_date.isoformat() if loan.start_date else None,
            "end_date": loan.end_date.isoformat() if loan.end_date else None,
            "loan_fund": loan.loan_fund.name if loan.loan_fund else None,
        }
        for loan in qs
    ]
    return JsonResponse({"count": len(data), "loans": data})

# Climate Shock Loans

A drought-triggered micro-finance platform built for ETHGlobal. When a climate oracle detects drought conditions, pre-qualified farmers can instantly request emergency loans — enforced and recorded on-chain via a Solidity smart contract on Ethereum Sepolia.

---

## What it does

1. A **climate oracle** monitors rainfall data (CHIRPS). When rainfall drops below the drought threshold, it calls `updateFromOracle(1)` on the smart contract, setting `droughtTriggered = true`.
2. Pre-qualified farmers can now request loans. Each request calls `requestLoan(amount)` on-chain. The contract enforces:
   - Farmer must be pre-qualified
   - Drought must be active
   - Amount must be within the loan product range ($55–$120)
   - Sufficient capital must remain in the reserve
3. On confirmation, the Django backend syncs its local `LoanFund` state from the contract and marks a `Loan` record as disbursed.
4. The live dashboard displays all activity — capital deployed, loans issued, on-chain tx hashes — updating in real time.

---

## Architecture

```
CHIRPS Data → Oracle → contract.updateFromOracle(1) → droughtTriggered = true
                                                              ↓
Farmer Request → Django → contract.requestLoan(amount) → confirmed on Sepolia
                                   ↓                              ↓
                          SimulationLog (DB)            LoanFund synced from contract
```

**Smart contract** is the single source of truth. Django never changes the fund balance until the blockchain confirms.

---

## Smart Contract (Sepolia)

**`ClimateLoanManager.sol`**

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract ClimateLoanManager {
    bool public droughtTriggered;
    uint256 public availableCapital = 100000;
    uint256 public loansIssued;
    uint256 public lastReserveCheck;
    uint256 public MIN_LOAN = 55;
    uint256 public MAX_LOAN = 120;

    mapping(address => bool) public prequalified;

    event DroughtTriggered(uint256 result);
    event DroughtReset();
    event LoanIssued(address farmer, uint256 amount);
    event FarmerPrequalified(address farmer);

    function prequalifyFarmer(address farmer) public { ... }
    function updateFromOracle(uint256 result) public { ... }  // result=1 triggers drought
    function resetDrought() public { ... }
    function requestLoan(uint256 amount) public { ... }
    function getReserveStatus() public view returns (bool, uint256, uint256) { ... }
}
```

Key functions:
| Function | Who calls it | When |
|---|---|---|
| `updateFromOracle(1)` | Oracle / admin | Drought detected |
| `resetDrought()` | Admin | After event ends |
| `prequalifyFarmer(addr)` | Admin | Farmer onboarding |
| `requestLoan(amount)` | Django backend | Each farmer request |
| `getReserveStatus()` | Django (read) | After each confirmation |

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Django 5.0.1, Python 3.12 |
| Frontend | Tailwind CSS (CDN), vanilla JS |
| Database | PostgreSQL (Heroku) / SQLite (local) |
| Blockchain | Ethereum Sepolia, web3.py 7.9.0 |
| RPC | Infura |
| Deployment | Heroku |
| Static files | WhiteNoise |
| Climate data | CHIRPS v2.0 (simulated) |

---

## Local setup

### 1. Clone and install

```bash
git clone <repo>
cd climate_shock_loans/climate_loans
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Environment variables

Create `climate_loans/.env`:

```
INFURA_URL=https://sepolia.infura.io/v3/<your-key>
PRIVATE_KEY=<your-wallet-private-key>
CONTRACT_ADDRESS=<deployed-contract-address>
```

### 3. Database

```bash
DJANGO_SETTINGS_MODULE=climate_loans.settings.local venv/bin/python manage.py migrate
```

### 4. Seed data

Creates 1,000 pre-qualified Ethiopian farmers with pending loans ($55–$120):

```bash
DJANGO_SETTINGS_MODULE=climate_loans.settings.local venv/bin/python manage.py seed_data
```

### 5. Run

```bash
DJANGO_SETTINGS_MODULE=climate_loans.settings.local venv/bin/python manage.py runserver
```

Visit `http://localhost:8000`

> **Important:** Use `venv/bin/python` explicitly — the system `python` alias may point to a different version with an incompatible web3 install.

---

## One-time contract setup

After deploying the contract, pre-qualify your simulation wallet:

```bash
DJANGO_SETTINGS_MODULE=climate_loans.settings.local venv/bin/python manage.py shell -c "
from loans.views import _get_w3, _raw_tx
w3, account, contract = _get_w3()
nonce = w3.eth.get_transaction_count(account.address)
tx = contract.functions.prequalifyFarmer(account.address).build_transaction({
    'from': account.address, 'nonce': nonce, 'gas': 80000, 'gasPrice': w3.eth.gas_price
})
signed = w3.eth.account.sign_transaction(tx, account.key)
receipt = w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(_raw_tx(signed)))
print('Prequalified:', receipt.status == 1)
"
```

Then trigger drought on-chain:

```bash
# Via Django shell or use the dashboard trigger button
from loans.views import _trigger_drought_on_chain
_trigger_drought_on_chain()
```

---

## Heroku deployment

```bash
heroku login
heroku git:remote -a climate-loans
git push heroku main

heroku run python manage.py migrate --app climate-loans
heroku run python manage.py seed_data --app climate-loans
```

Set config vars:

```bash
heroku config:set INFURA_URL=... PRIVATE_KEY=... CONTRACT_ADDRESS=...
heroku config:set DJANGO_SETTINGS_MODULE=climate_loans.settings.production
heroku config:set SECRET_KEY=...
```

---

## Data models

| Model | Purpose |
|---|---|
| `Farmer` | Pre-qualified farmer with location and bank details |
| `LoanProduct` | Loan parameters (min/max amount, term, grace period) |
| `LoanFund` | Capital pool — synced from contract after each confirmation |
| `Loan` | Individual loan record — moves from pending → disbursed on approval |
| `SimulationLog` | Approved loan history — persists the activity log across refreshes |
| `ClimateTrigger` | Climate event record — mirrors contract's `droughtTriggered` state |
| `MFI` | Microfinance institution linked to farmers and loan products |

---

## Dashboard features

- **Live drought status** — mirrors contract's `droughtTriggered`
- **Proof of Reserve** — shows available capital, verified via `getReserveStatus()`
- **Farmer simulation** — runs up to 10 farmers in sequence, each sending a real `requestLoan` tx and waiting for Sepolia confirmation before proceeding
- **Stop button** — halts the queue after the current in-flight transaction confirms
- **Activity log** — live feed of requests with tx hashes linked to Sepolia Etherscan, persists across page refreshes
- **KPI cards** — Pre-qualified farmers, Loans Issued, Capital Deployed, Capital Remaining — all live-updated
- **Approved Farmers table** — collapsible list of all confirmed on-chain loans
- **Secret reset controls** (footer `···` buttons) — reset fund to $100,000 or reset drought on-chain

---

## Project structure

```
climate_loans/
├── climate_loans/
│   ├── settings/
│   │   ├── common.py
│   │   ├── local.py
│   │   └── production.py
│   └── urls.py
├── loans/
│   ├── management/commands/
│   │   └── seed_data.py
│   ├── migrations/
│   ├── templates/loans/
│   │   └── dashboard.html
│   ├── admin.py
│   ├── models.py
│   ├── urls.py
│   └── views.py
├── static/
│   ├── report_icons/
│   └── (hero images, logo)
├── requirements.txt
├── runtime.txt          # python-3.12.9
└── Procfile
```

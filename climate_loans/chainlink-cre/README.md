# Chainlink CRE Workflow – Climate Shock Loans Oracle

This folder contains our Chainlink Runtime Environment (CRE) workflow used as the oracle layer for climate-triggered lending.

## What this does

The workflow:

1. Fetches rainfall data from an external API  
2. Determines whether a drought condition is met  
3. Aggregates the drought signal  
4. Writes the result on-chain  
5. Triggers loan availability for pre-qualified farmers  

## Why this matters

Smallholder farmers face significant downside risk from climate shocks.  
This workflow enables **automatic capital access when drought conditions occur**, reducing risk and enabling investment.

## Key Files

- `nav/workflow.ts`  
  Core CRE workflow logic:
  - Uses `HTTPClient` to fetch climate data  
  - Uses `ConsensusAggregationByFields` to determine drought  
  - Uses `DataFeedsCache.writeReport` to update on-chain state  

- `project.yaml`  
  Workflow configuration:
  - Defines API endpoint  
  - Defines execution schedule  
  - Defines chain + contract integration  

## How it fits into the system

```text
External Climate API
        ↓
Chainlink CRE Workflow (this folder)
        ↓
Smart Contract (drought trigger)
        ↓
Loan fund unlocks for farmers
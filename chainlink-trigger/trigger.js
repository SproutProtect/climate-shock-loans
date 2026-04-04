require("dotenv").config();
const axios = require("axios");
const { ethers } = require("ethers");

const API_URL = "http://127.0.0.1:4000/api/rainfall/?rainfall=4";

const provider = new ethers.JsonRpcProvider(process.env.INFURA_URL);
const wallet = new ethers.Wallet(process.env.PRIVATE_KEY, provider);

const abi = [
  "function updateFromOracle(uint256 result) public"
];

const contract = new ethers.Contract(
  process.env.CONTRACT_ADDRESS,
  abi,
  wallet
);

async function main() {
  console.log("🌧 Fetching rainfall data...");

  const response = await axios.get(API_URL);
  const data = response.data;

  console.log("Rainfall:", data.rainfall);
  console.log("Drought:", data.drought);

  if (data.drought === true) {
    console.log("🚨 Drought detected → triggering contract");

    const tx = await contract.updateFromOracle(1);
    await tx.wait();

    console.log("✅ Transaction sent:", tx.hash);
  } else {
    console.log("✅ No drought — nothing triggered");
  }
}

main().catch(console.error);
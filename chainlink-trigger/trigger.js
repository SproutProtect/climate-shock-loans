require("dotenv").config();
const { ethers } = require("ethers");

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

// Get CLI argument
const input = process.argv[2]; // "1" or "0"

async function main() {
  console.log("📥 Input received:", input);

  if (input !== "0" && input !== "1") {
    console.log("❌ Please provide 0 (no drought) or 1 (drought)");
    return;
  }

  const result = parseInt(input);

  if (result === 1) {
    console.log("🚨 Drought detected → activating loan system on-chain");

    const tx = await contract.updateFromOracle(1);
    await tx.wait();

    console.log("✅ Drought status updated on-chain");
    console.log("🔗 Tx:", tx.hash);
    console.log("➡️ Farmers can now begin requesting loans");
  } else {
    console.log("🌤 No drought → nothing triggered");
  }
}

main().catch(console.error);
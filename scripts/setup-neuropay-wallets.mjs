/**
 * setup-neuropay-wallets.mjs: Create the NanoPay Agent Network
 *
 * This script is updated to handle API keys exactly as required by the
 * @circle-fin/developer-controlled-wallets SDK.
 */

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";
import { fileURLToPath } from "node:url";
import {
  registerEntitySecretCiphertext,
  initiateDeveloperControlledWalletsClient,
} from "@circle-fin/developer-controlled-wallets";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUTPUT_DIR = path.join(__dirname, "../output");
const WALLET_SET_NAME = "NanoPay-Agent-Network";

async function main() {
  let apiKey = process.env.CIRCLE_API_KEY;
  if (!apiKey) {
    throw new Error("CIRCLE_API_KEY is required in .env");
  }

  // IMPORTANT: The SDK for Developer Controlled Wallets requires the FULL
  // TEST_API_KEY:id:secret format for authentication.
  // We removed the cleaning logic that was stripping the prefix.

  const envPath = path.join(__dirname, "../.env");

  // 1. Force Register New Entity Secret
  console.log("🚀 Force-registering a NEW NanoPay Entity Secret...");
  if (!fs.existsSync(OUTPUT_DIR)) {
    fs.mkdirSync(OUTPUT_DIR, { recursive: true });
  }

  const entitySecret = crypto.randomBytes(32).toString("hex");
  try {
    await registerEntitySecretCiphertext({
      apiKey,
      entitySecret,
      recoveryFileDownloadPath: OUTPUT_DIR,
    });
    console.log("✅ New Entity Secret registered successfully.");
  } catch (e) {
    console.error("❌ Registration failed:", e.message);
    if (e.message.includes("already been set")) {
      console.log("\n⚠️ ERROR: Circle does not allow overwriting an existing Entity Secret for a given API Key.");
      console.log("To fix this, you must either:");
      console.log("1. Create a NEW API Key in the Circle Console.");
      console.log("2. Use the existing CIRCLE_ENTITY_SECRET already in your .env.");
    }
    throw e;
  }

  const updateEnv = (key, value) => {
    let content = "";
    try { content = fs.readFileSync(envPath, "utf-8"); } catch (e) {}
    const regex = new RegExp(`^${key}=.*`, "m");
    if (regex.test(content)) {
      fs.writeFileSync(envPath, content.replace(regex, `${key}=${value}`), "utf-8");
    } else {
      fs.appendFileSync(envPath, `\n${key}=${value}\n`, "utf-8");
    }
  };

  updateEnv("CIRCLE_ENTITY_SECRET", entitySecret);

  // 2. Initialize Client
  const client = initiateDeveloperControlledWalletsClient({
    apiKey,
    entitySecret,
  });

  // 3. Create Wallet Set
  console.log("\n📦 Creating NanoPay Wallet Set...");
  const walletSetResponse = await client.createWalletSet({ name: WALLET_SET_NAME });
  const walletSet = walletSetResponse.data?.walletSet;
  if (!walletSet?.id) throw new Error("Wallet Set creation failed");
  console.log("✅ Wallet Set ID:", walletSet.id);

  // 4. Create 3 Wallets
  console.log("\n🏦 Creating Agent Wallets on ARC-TESTNET...");
  const walletsResponse = await client.createWallets({
    walletSetId: walletSet.id,
    blockchains: ["ARC-TESTNET"],
    count: 3,
    accountType: "EOA",
  });
  const wallets = walletsResponse.data?.wallets;

  if (!wallets || wallets.length < 3) throw new Error("Failed to create all 3 wallets");

  const [coordinator, specA, specB] = wallets;

  console.log("\n--- WALLET ASSIGNMENTS ---");
  console.log(`Coordinator: ${coordinator.id} | Address: ${coordinator.address}`);
  console.log(`Specialist A: ${specA.id} | Address: ${specA.address}`);
  console.log(`Specialist B: ${specB.id} | Address: ${specB.address}`);

  updateEnv("COORDINATOR_WALLET_ID", coordinator.id);
  updateEnv("SPECIALIST_A_WALLET_ID", specA.id);
  updateEnv("SPECIALIST_B_WALLET_ID", specB.id);
  updateEnv("COORDINATOR_WALLET_ADDRESS", coordinator.address);
  updateEnv("SPECIALIST_A_WALLET_ADDRESS", specA.address);
  updateEnv("SPECIALIST_B_WALLET_ADDRESS", specB.address);
  updateEnv("ARC_RPC_URL", process.env.ARC_RPC_URL || "https://rpc.testnet.arc.network/");
  updateEnv("IDENTITY_REGISTRY_ADDRESS", process.env.IDENTITY_REGISTRY_ADDRESS || "0x8004A818BFB912233c491871b3d84c89A494BD9e");
  updateEnv("REPUTATION_REGISTRY_ADDRESS", process.env.REPUTATION_REGISTRY_ADDRESS || "0x8004B663056A597Dffe9eCcC1965A193B7388713");
  updateEnv("VALIDATION_REGISTRY_ADDRESS", process.env.VALIDATION_REGISTRY_ADDRESS || "0x8004Cb1BF31DAf7788923b405b754f57acEB4272");

  fs.writeFileSync(
    path.join(OUTPUT_DIR, "nanopay-wallets.json"),
    JSON.stringify({ coordinator, specA, specB, walletSetId: walletSet.id }, null, 2),
    "utf-8"
  );

  console.log("\n💰 FUNDING REQUIRED:");
  console.log("1. Go to https://faucet.circle.com");
  console.log("2. Select 'Arc Testnet' network");
  console.log(`3. Paste Coordinator Address: ${coordinator.address}`);
  console.log("4. Click 'Send USDC'");

  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  await new Promise((resolve) =>
    rl.question("\nPress Enter once the COORDINATOR wallet has been funded... ", () => {
      rl.close();
      resolve();
    }),
  );

  // 5. Verification: Distribute funds to Specialists
  console.log("\n🧪 Verifying Value Flow: Sending 1 USDC to each Specialist...");
  const ARC_TESTNET_USDC = "0x3600000000000000000000000000000000000000";

  const targets = [
    { id: "Specialist A", addr: specA.address },
    { id: "Specialist B", addr: specB.address }
  ];

  for (const target of targets) {
    console.log(`Sending to ${target.id}...`);
    const tx = await client.createTransaction({
      blockchain: "ARC-TESTNET",
      walletAddress: coordinator.address,
      destinationAddress: target.addr,
      amount: ["1"],
      tokenAddress: ARC_TESTNET_USDC,
      fee: { type: "level", config: { feeLevel: "MEDIUM" } },
    });
    console.log(`Transaction submitted. ID: ${tx.data?.id}`);
  }

  console.log("\n✅ Setup Complete! Your .env is updated and funds are distributing.");
  console.log("Check balances on https://testnet.arcscan.app/");
}

main().catch((err) => {
  console.error("❌ Error:", err.message || err);
  process.exit(1);
});

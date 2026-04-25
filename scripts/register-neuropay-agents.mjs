import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { initiateDeveloperControlledWalletsClient } from "@circle-fin/developer-controlled-wallets";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUTPUT_DIR = path.join(__dirname, "../output");
const OUTPUT_FILE = path.join(OUTPUT_DIR, "erc8004-registrations.json");

const ARC_RPC_URL = process.env.ARC_RPC_URL || "https://rpc.testnet.arc.network/";
const IDENTITY_REGISTRY =
  process.env.IDENTITY_REGISTRY_ADDRESS ||
  "0x8004A818BFB912233c491871b3d84c89A494BD9e";
const TRANSFER_TOPIC =
  "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef";

const DEFAULT_METADATA_URI =
  process.env.METADATA_URI ||
  "ipfs://bafkreibdi6623n3xpf7ymk62ckb4bo75o3qemwkpfvp5i25j66itxvsoei";

function requireEnv(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} is required in .env`);
  }
  return value;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function toPaddedTopicAddress(address) {
  const normalized = address.toLowerCase().replace(/^0x/, "");
  return `0x${"0".repeat(24)}${normalized}`;
}

async function rpcCall(method, params) {
  const response = await fetch(ARC_RPC_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: Date.now(),
      method,
      params,
    }),
  });

  if (!response.ok) {
    throw new Error(`RPC request failed (${response.status})`);
  }

  const body = await response.json();
  if (body.error) {
    throw new Error(`RPC error: ${JSON.stringify(body.error)}`);
  }
  return body.result;
}

async function waitForTransaction(client, txId, label) {
  process.stdout.write(`  Waiting for ${label}`);
  for (let i = 0; i < 60; i += 1) {
    await sleep(2000);
    const tx = await client.getTransaction({ id: txId });
    const status = tx.data?.transaction?.state;

    if (status === "COMPLETE") {
      const txHash = tx.data?.transaction?.txHash;
      process.stdout.write(" done\n");
      return txHash;
    }

    if (status === "FAILED") {
      throw new Error(`${label} failed onchain`);
    }

    process.stdout.write(".");
  }

  throw new Error(`${label} timed out`);
}

async function resolveWalletAddress(client, label, walletId, walletAddress) {
  if (walletAddress) {
    return walletAddress;
  }

  if (!walletId) {
    throw new Error(`Missing wallet id/address for ${label}`);
  }

  const response = await client.getWallet({ id: walletId });
  const resolved = response.data?.wallet?.address;
  if (!resolved) {
    throw new Error(`Unable to resolve wallet address for ${label}`);
  }
  return resolved;
}

async function getLatestAgentIdForOwner(ownerAddress) {
  const latestHex = await rpcCall("eth_blockNumber", []);
  const latest = BigInt(latestHex);
  const range = 10000n;
  const from = latest > range ? latest - range : 0n;

  const logs = await rpcCall("eth_getLogs", [
    {
      address: IDENTITY_REGISTRY,
      fromBlock: `0x${from.toString(16)}`,
      toBlock: `0x${latest.toString(16)}`,
      topics: [TRANSFER_TOPIC, null, toPaddedTopicAddress(ownerAddress)],
    },
  ]);

  if (!Array.isArray(logs) || logs.length === 0) {
    throw new Error(`No Transfer logs found for owner ${ownerAddress}`);
  }

  const last = logs[logs.length - 1];
  return BigInt(last.topics[3]).toString();
}

async function registerAgentIdentity(client, label, walletAddress, metadataUri) {
  const createTx = await client.createContractExecutionTransaction({
    walletAddress,
    blockchain: "ARC-TESTNET",
    contractAddress: IDENTITY_REGISTRY,
    abiFunctionSignature: "register()",
    fee: { type: "level", config: { feeLevel: "MEDIUM" } },
  });

  const txId = createTx.data?.id;
  if (!txId) {
    throw new Error(`Missing transaction id for ${label}`);
  }

  const txHash = await waitForTransaction(client, txId, `${label} register()`);
  const agentId = await getLatestAgentIdForOwner(walletAddress);

  return {
    txId,
    txHash,
    agentId,
    explorer: txHash ? `https://testnet.arcscan.app/tx/${txHash}` : null,
  };
}

async function main() {
  const apiKey = requireEnv("CIRCLE_API_KEY");
  const entitySecret = requireEnv("CIRCLE_ENTITY_SECRET");

  const client = initiateDeveloperControlledWalletsClient({
    apiKey,
    entitySecret,
  });

  const walletSpecs = [
    {
      label: "Coordinator",
      walletId: process.env.COORDINATOR_WALLET_ID,
      walletAddress: process.env.COORDINATOR_WALLET_ADDRESS,
      metadataUri: process.env.COORDINATOR_METADATA_URI || DEFAULT_METADATA_URI,
    },
    {
      label: "Specialist A",
      walletId: process.env.SPECIALIST_A_WALLET_ID,
      walletAddress: process.env.SPECIALIST_A_WALLET_ADDRESS,
      metadataUri: process.env.SPECIALIST_A_METADATA_URI || DEFAULT_METADATA_URI,
    },
    {
      label: "Specialist B",
      walletId: process.env.SPECIALIST_B_WALLET_ID,
      walletAddress: process.env.SPECIALIST_B_WALLET_ADDRESS,
      metadataUri: process.env.SPECIALIST_B_METADATA_URI || DEFAULT_METADATA_URI,
    },
  ];

  if (!fs.existsSync(OUTPUT_DIR)) {
    fs.mkdirSync(OUTPUT_DIR, { recursive: true });
  }

  const results = [];
  console.log("Registering NanoPay agents on ERC-8004 IdentityRegistry...");
  console.log(`IdentityRegistry: ${IDENTITY_REGISTRY}`);

  for (const spec of walletSpecs) {
    const address = await resolveWalletAddress(
      client,
      spec.label,
      spec.walletId,
      spec.walletAddress,
    );

    console.log(`\n- ${spec.label}`);
    console.log(`  Wallet: ${address}`);
    console.log(`  Metadata: ${spec.metadataUri}`);

    const registration = await registerAgentIdentity(
      client,
      spec.label,
      address,
      spec.metadataUri,
    );

    console.log(`  Agent ID: ${registration.agentId}`);
    if (registration.explorer) {
      console.log(`  Tx: ${registration.explorer}`);
    }

    results.push({
      ...spec,
      walletAddress: address,
      identityRegistry: IDENTITY_REGISTRY,
      ...registration,
    });
  }

  fs.writeFileSync(
    OUTPUT_FILE,
    JSON.stringify(
      {
        generatedAt: new Date().toISOString(),
        identityRegistry: IDENTITY_REGISTRY,
        rpc: ARC_RPC_URL,
        agents: results,
      },
      null,
      2,
    ),
    "utf-8",
  );

  console.log("\nRegistration complete.");
  console.log(`Output: ${OUTPUT_FILE}`);
}

main().catch((error) => {
  console.error("Error:", error.message || error);
  process.exit(1);
});

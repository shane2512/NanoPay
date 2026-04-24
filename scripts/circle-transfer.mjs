import { initiateDeveloperControlledWalletsClient } from "@circle-fin/developer-controlled-wallets";

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 1) {
    const key = argv[i];
    if (!key.startsWith("--")) continue;
    const value = argv[i + 1];
    args[key.slice(2)] = value;
    i += 1;
  }
  return args;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForComplete(client, txId, maxAttempts = 60) {
  for (let i = 0; i < maxAttempts; i += 1) {
    await sleep(2000);
    const tx = await client.getTransaction({ id: txId });
    const transaction = tx.data?.transaction;
    if (transaction?.state === "COMPLETE") {
      return transaction;
    }
    if (transaction?.state === "FAILED") {
      throw new Error(`Transaction ${txId} failed`);
    }
  }
  throw new Error(`Transaction ${txId} timed out`);
}

async function main() {
  const apiKey = process.env.CIRCLE_API_KEY;
  const entitySecret = process.env.CIRCLE_ENTITY_SECRET;
  if (!apiKey || !entitySecret) {
    throw new Error("CIRCLE_API_KEY and CIRCLE_ENTITY_SECRET are required");
  }

  const args = parseArgs(process.argv.slice(2));
  const destination = args.destination;
  const amount = args.amount;
  if (!destination || !amount) {
    throw new Error("--destination and --amount are required");
  }

  const client = initiateDeveloperControlledWalletsClient({
    apiKey,
    entitySecret,
  });

  let senderAddress = args.sender || process.env.COORDINATOR_WALLET_ADDRESS;
  if (!senderAddress) {
    const walletId = process.env.COORDINATOR_WALLET_ID;
    if (!walletId) {
      throw new Error("COORDINATOR_WALLET_ADDRESS or COORDINATOR_WALLET_ID is required");
    }
    const wallet = await client.getWallet({ id: walletId });
    senderAddress = wallet.data?.wallet?.address;
  }

  if (!senderAddress) {
    throw new Error("Unable to resolve sender wallet address");
  }

  const tx = await client.createTransaction({
    walletAddress: senderAddress,
    blockchain: "ARC-TESTNET",
    tokenAddress: "0x3600000000000000000000000000000000000000",
    destinationAddress: destination,
    amount: [amount],
    fee: { type: "level", config: { feeLevel: "MEDIUM" } },
  });

  const txId = tx.data?.id;
  if (!txId) {
    throw new Error("Transfer response missing transaction id");
  }

  const completed = await waitForComplete(client, txId);
  const txHash = completed.txHash;
  if (!txHash) {
    throw new Error("Completed transaction missing txHash");
  }

  const payload = {
    txId,
    txHash,
    sender: senderAddress,
    destination,
    amount,
    state: completed.state,
  };

  process.stdout.write(JSON.stringify(payload));
}

main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});

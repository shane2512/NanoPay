import uvicorn
from agents.base_agent import BaseExpertAgent, create_agent_app
import os

# Load specific config for this agent
# In a real deployment, these would come from .env or a config file
DOMAIN = "Finance/Biotech"
WALLET_ID = os.getenv("SPECIALIST_A_WALLET_ID")
WALLET_ADDRESS = os.getenv("SPECIALIST_A_WALLET_ADDRESS")
PRICE = 0.003

if not WALLET_ID:
    raise ValueError("SPECIALIST_A_WALLET_ID is required in .env")

agent = BaseExpertAgent(
    domain=DOMAIN,
    wallet_id=WALLET_ID,
    wallet_address=WALLET_ADDRESS,
    price=PRICE,
)
app = create_agent_app(agent)

if __name__ == "__main__":
    print(f"Starting {DOMAIN} Agent on port 8001...")
    uvicorn.run(app, host="0.0.0.0", port=8001)

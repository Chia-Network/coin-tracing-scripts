import asyncio

from chia.cmds.wallet_funcs import print_balance
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH


async def get_coins():
    config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
    try:
        client = await FullNodeRpcClient.create(config["self_hostname"], config["full_node"]["rpc_port"],
                                                DEFAULT_ROOT_PATH, config)
    except Exception as e:
        raise Exception(f"Failed to create RPC client: {e}")

    block = await client.get_block_record_by_height(1)
    assert block is not None

    for coin in block.reward_claims_incorporated:
        print(f"| 0x{coin.name().hex()}  |  {print_balance(coin.amount,1000000000000,'xch')} ")

    client.close()

asyncio.run(get_coins())

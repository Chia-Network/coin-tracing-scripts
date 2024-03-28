import asyncio
import hashlib
import sys
from typing import Dict, List, Optional

from chia.cmds.wallet_funcs import print_balance
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.byte_types import hexstr_to_bytes
from chia.util.condition_tools import conditions_dict_for_solution
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint32


# lineage.py <new_coin_id>
#
# For the spend actually creating the coin, come up with the following value:
# sha256(coinID+<the value from CREATE_COIN_ANNOUNCEMENT/60)
# This value will be present as a 61/ASSERT_COIN_ANNOUNCEMENT on every other coin that is an input to the coin
#
# This assumes the transaction was created with our standard wallet, does not apply to custom wallets which may do
# things in a less secure manner

async def get_inputs():
    coin_hex = sys.argv[1]
    coin_bytes = bytes32.from_bytes(hexstr_to_bytes(coin_hex))
    print(f"Attempting to determine input coins for:     0x{coin_bytes.hex()}")

    config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
    try:
        client = await FullNodeRpcClient.create(config["self_hostname"], config["full_node"]["rpc_port"],
                                                DEFAULT_ROOT_PATH, config)
    except Exception as e:
        raise Exception(f"Failed to create RPC client: {e}")

    coin_record = await client.get_coin_record_by_name(coin_bytes)
    assert coin_record is not None

    if coin_record.coinbase:
        print()
        print("This coin has no parent (farming reward or genesis)")
        client.close()
        return

    primary_parent = await client.get_coin_record_by_name(coin_record.coin.parent_coin_info)
    assert primary_parent is not None

    conditions = await get_conditions_for_coin(client, primary_parent)

    assert conditions is not None

    input_coins: List[CoinRecord] = []

    for create_coin_announcement in conditions.get(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, []):
        assert len(create_coin_announcement.vars) == 1
        assertValue = hashlib.sha256(
            coin_record.coin.parent_coin_info +
            create_coin_announcement.vars[0]
        ).digest()
        print(f"sha256(coinID+CREATE_COIN_ANNOUNCEMENT) is:  0x{assertValue.hex()}")
        print(f"locating spent coins with ASSERT_COIN_ANNOUNCEMENT 0x{assertValue.hex()}")

        # Get all additions and removals for the block
        block = await client.get_block_record_by_height(coin_record.confirmed_block_index)
        assert block is not None
        _, removals = await client.get_additions_and_removals(block.header_hash)
        for removal in removals:
            conditions = await get_conditions_for_coin(client, removal)
            assert conditions is not None
            for assert_coin_announcement in conditions.get(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, []):
                assert len(assert_coin_announcement.vars) == 1
                if assert_coin_announcement.vars[0] == assertValue:
                    input_coins.append(removal)

    print()
    print("COIN INPUTS:")
    print("|  Parent Coin                                                         |  Value          ")
    print(f"|  0x{primary_parent.name.hex()}  |  {print_balance(primary_parent.coin.amount,1000000000000,'xch')} ")
    for input_coin in input_coins:
        print(f"|  0x{input_coin.name.hex()}  |  {print_balance(input_coin.coin.amount,1000000000000,'xch')} ")

    client.close()


async def get_conditions_for_coin(client: FullNodeRpcClient, coin: CoinRecord):
    # Height for this is the height the coin was spent at
    puzz_solution = await client.get_puzzle_and_solution(coin.name, coin.spent_block_index)

    assert puzz_solution is not None

    # For the listed parent coin, we need to calculate sha256(coinID+<CREATE_COIN_ANNOUNCEMENT>)
    # The value will match any other removal's ASSERT_COIN_ANNOUNCEMENT
    conditions = conditions_dict_for_solution(
        puzz_solution.puzzle_reveal,
        puzz_solution.solution,
        DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM)

    return conditions


asyncio.run(get_inputs())

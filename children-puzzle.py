import asyncio
import hashlib
import sys
from typing import Dict, List, Optional

from chia.cmds.wallet_funcs import print_balance
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.byte_types import hexstr_to_bytes
from chia.util.condition_tools import conditions_dict_for_solution
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint32, uint64


# children-puzzle.py <spent_coin_id>
#
# For the spend actually creating the coin, come up with the following value:
# sha256(puzzlehash+<the value from CREATE_PUZZLE_ANNOUNCEMENT/62)
# This value will be present as a 63/ASSERT_COIN_ANNOUNCEMENT on every other coin that is an input to the coin

async def get_outputs():
    coin_hex = sys.argv[1]
    coin_bytes = bytes32.from_bytes(hexstr_to_bytes(coin_hex))
    print(f"Attempting to determine output coins for:     0x{coin_bytes.hex()}")

    config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
    try:
        client = await FullNodeRpcClient.create(config["self_hostname"], config["full_node"]["rpc_port"],
                                                DEFAULT_ROOT_PATH, config)
    except Exception as e:
        raise Exception(f"Failed to create RPC client: {e}")

    coin_record = await client.get_coin_record_by_name(coin_bytes)
    assert coin_record is not None

    if coin_record.spent_block_index == 0:
        print("Coin is not spent!")
        client.close()
        return

    print(f"Coin was spent at height: {coin_record.spent_block_index}")

    conditions = await get_conditions_for_coin(client, coin_record)

    assert conditions is not None

    output_coins: List[Coin] = []

    if ConditionOpcode.CREATE_COIN in conditions and ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT not in conditions and ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT not in conditions:
        print("Could not find CREATE_PUZZLE_ANNOUNCEMENT or ASSERT_PUZZLE_ANNOUNCEMENT")
        # coins = coins_from_create_coin_condition(conditions, coin_bytes)
        # output_coins.extend(coins)
    else:
        if ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT in conditions:
            assert ConditionOpcode.CREATE_COIN in conditions

            for create_puzzle_announcement in conditions.get(ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, []):
                assert len(create_puzzle_announcement.vars) == 1
                print(f"Create puzzle announcement message is {create_puzzle_announcement.vars[0].hex()}")
                print(f"Coin puzzle hash is                   {coin_record.coin.puzzle_hash.hex()}")
                assertValue = hashlib.sha256(
                    coin_record.coin.puzzle_hash +
                    create_puzzle_announcement.vars[0]
                ).digest()
                print(f"sha256(coinID+CREATE_PUZZLE_ANNOUNCEMENT) is:          0x{assertValue.hex()}")
                print(f"locating created coins with ASSERT_PUZZLE_ANNOUNCEMENT 0x{assertValue.hex()}")
                # At this point, we could finish down this branch, to find any other coins spent in this same TX
                # which could potentially reveal "sibling" coins

            coins = coins_from_create_coin_condition(conditions, coin_bytes)
            output_coins.extend(coins)
        elif ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT in conditions:
            assert ConditionOpcode.CREATE_COIN not in conditions

            # Keep track of all the asserts we're interested in here
            asserts: List[bytes] = []
            for assert_puzzle_announcement in conditions.get(ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, []):
                assert len(assert_puzzle_announcement.vars) == 1
                asserts.append(assert_puzzle_announcement.vars[0])

            # Get all additions and removals for the block to find things actually creating coins
            block = await client.get_block_record_by_height(coin_record.spent_block_index)
            assert block is not None
            _, removals = await client.get_additions_and_removals(block.header_hash)
            for removal in removals:
                conditions = await get_conditions_for_coin(client, removal)
                assert conditions is not None
                if ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT in conditions:
                    for create_puzzle_announcement in conditions.get(ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, []):
                        assert len(create_puzzle_announcement.vars) == 1
                        assertValue = hashlib.sha256(
                            removal.coin.puzzle_hash +
                            create_puzzle_announcement.vars[0]
                        ).digest()

                        # If this is an assert we care about, based on the COIN_SPENT_ANNOUNCEMENTS
                        if assertValue in asserts:
                            assert ConditionOpcode.CREATE_COIN in conditions
                            coins = coins_from_create_coin_condition(conditions, removal.coin.name())
                            output_coins.extend(coins)

    print()
    print("COIN Outputs:")
    print("|  Coin ID                                                             |  Value          ")
    for output_coin in output_coins:
        print(f"|  0x{output_coin.name().hex()}  |  {print_balance(output_coin.amount, 1000000000000, 'xch')} ")

    client.close()


def coins_from_create_coin_condition(conditions, parent_coin_info: bytes32) -> List[Coin]:
    output_coins: List[Coin] = []

    for create_coin in conditions.get(ConditionOpcode.CREATE_COIN, []):
        puzzle_hash = create_coin.vars[0]
        amount = int.from_bytes(create_coin.vars[1], byteorder='big')
        output_coins.append(Coin(parent_coin_info, puzzle_hash, amount))

    return output_coins


async def get_conditions_for_coin(client: FullNodeRpcClient, coin: CoinRecord):
    # Height for this is the height the coin was spent at
    puzz_solution = await client.get_puzzle_and_solution(coin.name, coin.spent_block_index)

    assert puzz_solution is not None

    # For the listed parent coin, we need to calculate sha256(coinID+<CREATE_COIN_ANNOUNCEMENT>)
    # The value will match any other removal's ASSERT_COIN_ANNOUNCEMENT
    _, conditions, _ = conditions_dict_for_solution(
        puzz_solution.puzzle_reveal,
        puzz_solution.solution,
        DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM)

    return conditions


asyncio.run(get_outputs())

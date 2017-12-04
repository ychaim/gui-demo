# -*- coding: utf-8 -*-
"""Api to local database synchronization by api method"""
import logging
from binascii import unhexlify
from datetime import datetime

from app import enums
from app.models.vote import Vote
from app.tools.address import public_key_to_address
from app.responses import Getblockchaininfo
from app.signals import signals
from app.backend.rpc import get_active_rpc_client
from app.enums import Stream
from app.helpers import batchwise
from app.models import Address, Permission, Transaction, PendingVote, data_db, Block, Profile
from app.tools.validators import is_valid_username

log = logging.getLogger(__name__)

permission_candidates = ['admin', 'mine', 'issue', 'create']


def getinfo():
    """Update latest wallet balance on current profile"""
    client = get_active_rpc_client()
    profile = Profile.get_active()
    result = client.getinfo()['result']

    if result['balance'] != profile.balance:
        profile.balance = result['balance']
        profile.save()


def getblockchaininfo():
    """Emit headers and blocks (block sync status)"""
    client = get_active_rpc_client()
    result = client.getblockchaininfo()['result']
    # Todo: Maybe track headers/blocks on Profile db model
    signals.getblockchaininfo.emit(Getblockchaininfo(**result))
    return result


def getruntimeparams():
    """Update wallet main address on current profile"""
    client = get_active_rpc_client()
    profile = Profile.get_active()
    result = client.getruntimeparams()['result']

    if result['handshakelocal'] != profile.address:
        profile.address = result['handshakelocal']
        profile.save()


def process_blocks():
    """
    Find last valid Block, delete every Block above in DB and get all Blocks above from Node.
    Process through new Blocks:
    Add them to DB.
    Process through all transactions in block.
    """
    client = get_active_rpc_client()

    ### get last valid block in DB ###
    last_valid_height = -1
    last_block_is_valid = False
    while not last_block_is_valid:
        if data_db().query(Block).count() == 0:
            break
        latest_block = data_db().query(Block).order_by(Block.height.desc()).first()
        try:
            block_from_chain = client.getblock(hash_or_height='{}'.format(latest_block.height))['result']
        except Exception as e:
            log.debug(e)
            return
        if latest_block.hash == unhexlify(block_from_chain['hash']):
            last_block_is_valid = True
            last_valid_height = latest_block.height
        else:
            data_db().delete(latest_block)

    ### process new blocks ###
    block_count_node = client.getblockcount()['result']
    for batch in batchwise(range(last_valid_height+1, block_count_node), 100):
        new_blocks = []
        try:
            answer = client.listblocks(batch)
            if answer['error'] is None:
                new_blocks = answer['result']
            else:
                log.debug(answer['error'])
                return
        except Exception as e:
            log.debug(e)
            return

        for block in new_blocks:
            block_obj = Block(
                hash = unhexlify(block['hash']),
                height=block['height'],
                time=datetime.fromtimestamp(block['time']),
            )
            data_db().add(block_obj)
            if process_transactions(block['height']):
                data_db().commit()
            else:
                data_db().rollback()
                return
    if last_block_is_valid != block_count_node:
        process_permissions()


def process_transactions(block_height):
    client = get_active_rpc_client()

    try:
        block = client.getblock(hash_or_height='{}'.format(block_height))['result']
    except Exception as e:
        log.debug(e)
        return False
    for txid in block['tx']:
        try:
            tx = client.getrawtransaction(txid)
        except Exception as e:
            log.debug(e)
            return False
        # todo: look if we need this tx and if we do add it to db
    return True

def process_permissions():
    #todo: check if we have new perms / votes
    client = get_active_rpc_client()

    try:
        perms = client.listpermissions()['result']
    except Exception as e:
        log.debug(e)
        return

    data_db().query(Permission).delete()
    data_db().query(PendingVote).delete()

    for perm in perms:
        perm_type = perm['type']
        perm_start = perm['startblock']
        perm_end = perm['endblock']
        address = perm['address']

        create_address_if_not_exists(address)

        if perm_type not in [enums.ISSUE, enums.CREATE, enums.MINE, enums.ADMIN]:
            continue

        perm_obj = Permission(
            address=address,
            perm_type=perm_type,
            start_block=perm_start,
            end_block=perm_end
        )
        data_db().add(perm_obj)
        data_db().commit()

        for vote in perm['pending']:
            start_block = vote['startblock']
            end_block = vote['endblock']
            # If candidate has already the permission continue.
            if start_block == perm['startblock'] and end_block == perm['endblock']:
                continue
            for admin in vote['admins']:
                create_address_if_not_exists(admin)
                vote_obj = PendingVote(
                    address_from=admin,
                    address_to=address,
                    perm_type=perm_type,
                    start_block=start_block,
                    end_block=end_block
                )
                data_db().add(vote_obj)
                data_db().commit()


def create_address_if_not_exists(address):
    if data_db().query(Address).filter(Address.address == address).count() == 0:
        address_obj = Address(address=address)
        data_db().add(address_obj)
        data_db().commit()

def listwallettransactions():
    pass
#     client = get_active_rpc_client()
#     txs = client.listwallettransactions(10000000)
#     if not txs:
#         log.warning('no transactions from api')
#         return
#     balance = 0
#     new_transactions = []
#     new_confirmations = []
#     with data_db.atomic():
#         for tx in txs['result']:
#             if tx['valid']:
#                 txid = tx['txid']
#                 dt = datetime.fromtimestamp(tx['time'])
#
#                 comment = ''
#                 txtype = Transaction.PAYMENT
#                 if tx['permissions']:
#                     txtype = Transaction.VOTE
#
#                 items = tx['items']
#                 if items:
#                     first_item = items[0]
#                     if first_item['type'] == 'stream':
#                         txtype = Transaction.PUBLISH
#                         comment = 'Stream:"' + first_item['name'] + '", Key: "' + first_item['key'] + '"'
#
#                 if tx.get('generated'):
#                     txtype = Transaction.MINING_REWARD
#
#                 # local comments have the highest priority
#                 if 'comment' in tx:
#                     comment = tx.get('comment')
#
#                 amount = tx['balance']['amount']
#                 balance += amount
#                 confirmations = tx['confirmations']
#
#                 tx_obj, created = Transaction.get_or_create(
#                     txid=txid, defaults=dict(
#                         datetime=dt,
#                         txtype=txtype,
#                         comment=comment,
#                         amount=amount,
#                         balance=balance,
#                         confirmations=confirmations
#                     )
#                 )
#                 if created:
#                     new_transactions.append(tx_obj)
#                 elif tx_obj.confirmations == 0 and confirmations != 0:
#                     tx_obj.confirmations = confirmations
#                     new_confirmations.append(tx_obj)
#                     tx_obj.save()
#
#     if len(new_transactions) > 0 or len(new_confirmations) > 0:
#         signals.listwallettransactions.emit(new_transactions, new_confirmations)
#     return len(new_transactions) != 0


def listpermissions():
    pass
    # client = get_active_rpc_client()
    # node_height = client.getblockcount()['result']
    #
    # perms = client.listpermissions()
    # if not perms:
    #     log.warning('no permissions from api')
    #     return
    # new_perms, new_votes = False, False
    #
    # Permission.delete().execute()
    # PendingVote.delete().execute()
    #
    # admin_addresses = set()
    # miner_addresses = set()
    #
    # with data_db.atomic():
    #     profile = Profile.get_active()
    #
    #     for perm in perms['result']:
    #         perm_type = perm['type']
    #         perm_start = perm['startblock']
    #         perm_end = perm['endblock']
    #
    #         if perm_type not in Permission.PERM_TYPES:
    #             continue
    #
    #         if perm_type == Permission.ADMIN and perm_start < node_height < perm_end:
    #             admin_addresses.add(perm['address'])
    #
    #         if perm_type == Permission.MINE and perm_start < node_height < perm_end:
    #             miner_addresses.add(perm['address'])
    #
    #         addr_obj, created = Address.get_or_create(address=perm['address'])
    #
    #         for vote in perm['pending']:
    #             # If candidate has already the permission continue.
    #             if vote['startblock'] == perm['startblock'] and vote['endblock'] == perm['endblock']:
    #                 continue
    #             start_block = vote['startblock']
    #             end_block = vote['endblock']
    #             # new stuff start
    #             for admin in vote['admins']:
    #                 admin_obj, created = Address.get_or_create(address=admin)
    #                 vote_obj, created = PendingVote.get_or_create(
    #                     address=addr_obj, perm_type=perm_type, start_block=start_block, end_block=end_block,
    #                     given_from=admin_obj
    #                 )
    #                 vote_obj.set_vote_type()
    #             # new stuff end
    #             approbations = len(vote['admins'])
    #             # TODO: Fix: current time of syncing is not the time of first_vote!
    #
    #         start_block = perm['startblock']
    #         end_block = perm['endblock']
    #         # TODO Why get_or_create ... we just deleted all Permission objects
    #         perm_obj, created = Permission.get_or_create(
    #             address=addr_obj, perm_type=perm_type, defaults=dict(start_block=start_block, end_block=end_block)
    #         )
    #         if created:
    #             new_perms = True
    #         else:
    #             perm_obj.save()
    #
    # new_is_admin = profile.address in admin_addresses
    # if profile.is_admin != new_is_admin:
    #     profile.is_admin = new_is_admin
    #
    # new_is_miner = profile.address in miner_addresses
    # if profile.is_miner != new_is_miner:
    #     profile.is_miner = new_is_miner
    #
    # if profile.dirty_fields:
    #     profile.save()
    #
    # # Todo: maybe only trigger table updates on actual change?
    # signals.listpermissions.emit()  # triggers community tab updates
    # signals.votes_changed.emit()  # triggers community tab updates
    # return {'new_perms': new_perms, 'new_votes': new_votes}


def liststreamitems_alias():
    """
    Sample stream item (none verbose):
    {
        'blocktime': 1505905511,
        'confirmations': 28948,
        'data': '4d696e65722031',
        'key': 'Miner_1',
        'publishers': ['1899xJpqZN3kMQdpvTxESWqykxgFJwRddCE4Tr'],
        'txid': 'caa1155e719803b9f39096860519a5e08e78214245ae9822beeea2b37a656178'
    }
    """

    pass
    # client = get_active_rpc_client()
    #
    # # TODO read and process only fresh stream data by storing a state cursor between runs
    # # TODO read stream items 100 at a time
    # stream_items = client.liststreamitems(Stream.alias.name, count=100000)
    # if not stream_items['result']:
    #     log.debug('got no items from stream alias')
    #     return 0
    #
    # by_addr = {}  # address -> alias
    # reseved = set()  # reserved aliases
    #
    # # aggregate the final state of address to alias mappings from stream
    # for item in stream_items['result']:
    #     confirmations = item['confirmations']
    #     alias = item['key']
    #     address = item['publishers'][0]
    #     data = item['data']
    #     num_publishers = len(item['publishers'])
    #
    #     # Sanity checks
    #     if confirmations < 1:
    #         log.debug('ignore alias - 0 confirmations for %s -> %s' % (address, alias))
    #         continue
    #     if data:
    #         log.debug('ignore alias - alias item "%s" with data "%s..."' % (alias, data[:8]))
    #         continue
    #     if not is_valid_username(alias):
    #         log.debug('ignore alias - alias does not match our regex: %s' % alias)
    #         continue
    #     if num_publishers != 1:
    #         log.debug('ignore alias - alias has multiple publishers: %s' % alias)
    #         continue
    #     if alias in reseved:
    #         log.debug('ignore alias - alias "%s" already reserved by "%s"' % (alias, address))
    #         continue
    #
    #     is_new_address = address not in by_addr
    #
    #     if is_new_address:
    #         by_addr[address] = alias
    #         reseved.add(alias)
    #         continue
    #
    #     is_alias_change = by_addr[address] != alias
    #
    #     if is_alias_change:
    #         log.debug('change alias of %s from %s to %s' % (address, by_addr[address], alias))
    #         # reserve new name
    #         reseved.add(alias)
    #         # release old name
    #         reseved.remove(by_addr[address])
    #         # set new name
    #         by_addr[address] = alias
    #         continue
    #
    # # update database
    # profile = Profile.get_active()
    # new_main_alias = by_addr.get(profile.address)
    # if new_main_alias and profile.alias != new_main_alias:
    #     log.debug('sync found new alias. profile.alias from %s to %s' % (profile.alias, new_main_alias))
    #     profile.alias = new_main_alias
    #     profile.save()
    #
    # with data_db.atomic():
    #     old_addrs = set(Address.select(Address.address, Address.alias).tuples())
    #     new_addrs = set(by_addr.items())
    #     # set of elements that are only in new_addr but not in old_addr
    #     changed_addrs = new_addrs - old_addrs
    #     new_rows = [dict(address=i[0], alias=i[1]) for i in changed_addrs]
    #     if new_rows:
    #         log.debug('adding new aliases %s' % changed_addrs)
    #         # insert rows 100 at a time.
    #         for idx in range(0, len(new_rows), 100):
    #             Address.insert_many(new_rows[idx:idx + 100]).upsert(True).execute()
    #
    # return len(changed_addrs)


getblock_proccessed_height = 1


def getblock():
    """Process detailed data from individual blocks to find last votes from guardians"""
    pass
    # TODO cleanup this deeply nested mess :)

    # client = get_active_rpc_client()
    # global getblock_proccessed_height
    # blockchain_params = client.getblockchainparams()['result']
    # pubkeyhash_version = blockchain_params['address-pubkeyhash-version']
    # checksum_value = blockchain_params['address-checksum-value']
    #
    # block_objs = Block.multi_tx_blocks().where(Block.height > getblock_proccessed_height)
    #
    # votes_changed = False
    #
    # with data_db.atomic():
    #     for block_obj in block_objs:
    #         height = block_obj.height
    #         block_info = client.getblock("{}".format(height))['result']
    #         for txid in block_info['tx']:
    #             transaction = client.getrawtransaction(txid, 4)
    #             if transaction['error'] is None:
    #                 if 'vout' in transaction['result']:
    #                     vout = transaction['result']['vout']
    #                     permissions = []
    #                     start_block = None
    #                     end_block = None
    #                     for vout_key, entry in enumerate(vout):
    #                         if len(entry['permissions']) > 0:
    #                             for key, perm in entry['permissions'][0].items():
    #                                 if perm and key in permission_candidates:
    #                                     permissions.append(key)
    #                                 if key == 'startblock':
    #                                     start_block = perm
    #                                 if key == 'endblock':
    #                                     end_block = perm
    #                             in_entry = transaction['result']['vin'][vout_key]
    #                             public_key = in_entry['scriptSig']['asm'].split(' ')[1]
    #                             from_pubkey = public_key_to_address(public_key, pubkeyhash_version, checksum_value)
    #                             given_to = entry['scriptPubKey']['addresses']
    #                             for addr in given_to:
    #                                 log.debug(
    #                                     'Grant or Revoke {} given by {} to {} at time {}'.format(
    #                                         permissions, from_pubkey, addr, block_obj.time)
    #                                 )
    #                                 addr_from_obj, _ = Address.get_or_create(address=from_pubkey)
    #                                 addr_to_obj, _ = Address.get_or_create(address=addr)
    #                                 vote_obj, created = Vote.get_or_create(
    #                                     txid=txid, defaults=dict(
    #                                         from_address=addr_from_obj,
    #                                         to_address_id=addr_to_obj,
    #                                         time=block_obj.time
    #                                     )
    #                                 )
    #                                 if created:
    #                                     votes_changed = True
    #
    #         getblock_proccessed_height = height
    #
    # if votes_changed:
    #     signals.votes_changed.emit()


def listblocks() -> int:
    """Synch block data from node

    :return int: number of new blocks synched to database
    """

    # client = get_active_rpc_client()
    #
    # # height_node = client.getblockcount()['result']
    # # latest_block_obj = Block.select().order_by(Block.height.desc()).first()
    # #
    # # last_valid_height = latest_block_obj.height
    # # block_from_chain = client.getblock(hash_or_height=latest_block_obj.height)['result']
    # # if latest_block_obj.hash !=
    # #     for i in range(height_db, -1, -1):
    # #        current_block = client.listblocks("{}-{}".format(i, i))[0]
    # #
    # #         if current_block['hash'] != Block.select(Block.hash).where(Block.height == i).scalar():
    # #             fork_happened = True
    # #         else:
    # #             if fork_happened:
    # #             +                Block.delete().where(Block.height > i)
    # #         +
    # #         break
    # #
    # # synced = 0
    #
    # for block in new_blocks['result']:
    #
    #     addr_obj, adr_created = Address.get_or_create(address=block['miner'])
    #     block_obj, blk_created = Block.get_or_create(
    #         hash=unhexlify(block['hash']),
    #         defaults=dict(
    #             time=datetime.fromtimestamp(block['time']),
    #             miner=addr_obj,
    #             txcount=block['txcount'],
    #             height=block['height'],
    #         )
    #     )
    #     if blk_created:
    #         synced += 1
    #
    #     log.debug('Synced block {}'.format(block_obj.height))
    #     signals.database_blocks_updated.emit(block_obj.height, height_node)
    # log.debug('Synced {} blocks total.'.format(synced))
    # return synced


if __name__ == '__main__':
    import app
    app.init()
    process_permissions()

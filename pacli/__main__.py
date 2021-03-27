from typing import Optional, Union
from decimal import Decimal ### ADDED ### 
import operator
import functools
import fire
import random
import pypeerassets as pa
import json
from prettyprinter import cpprint as pprint

from pypeerassets.pautils import (amount_to_exponent,
                                  exponent_to_amount,
                                  parse_card_transfer_metainfo,
                                  parse_deckspawn_metainfo,
                                  read_tx_opreturn ### ADDED ###
                                  )
from pypeerassets.transactions import NulldataScript, TxIn ### ADDED ###
from pypeerassets.__main__ import get_card_transfer
from pypeerassets.at.dt_entities import SignallingTransaction, LockingTransaction, DonationTransaction, VotingTransaction
from pypeerassets.at.transaction_formats import getfmt, PROPOSAL_FORMAT, SIGNALLING_FORMAT, LOCKING_FORMAT, DONATION_FORMAT, VOTING_FORMAT
from pypeerassets.at.dt_misc_utils import get_votestate, create_unsigned_tx, get_proposal_state

from pacli.provider import provider
from pacli.config import Settings
from pacli.keystore import init_keystore, set_new_key, delete_key, get_key, load_key ### MODIFIED ###
from pacli.tui import print_deck_info, print_deck_list
from pacli.tui import print_card_list
from pacli.export import export_to_csv
from pacli.utils import (cointoolkit_verify,
                         signtx,
                         sendtx)
from pacli.coin import Coin
from pacli.config import (write_default_config,
                          conf_file,
                          default_conf,
                          write_settings)
import pacli.dt_utils as du

class Config:

    '''dealing with configuration'''

    def default(self) -> None:
        '''revert to default config'''

        write_default_config(conf_file)

    def set(self, key: str, value: Union[str, bool]) -> None:
        '''change settings'''

        if key not in default_conf.keys():
            raise({'error': 'Invalid setting key.'})

        write_settings(key, value)


class Address:

    '''my personal address'''

    def show(self, pubkey: bool=False, privkey: bool=False, wif: bool=False) -> str:
        '''print address, pubkey or privkey'''

        if pubkey:
            return Settings.key.pubkey
        if privkey:
            return Settings.key.privkey
        if wif:
            return Settings.key.wif

        return Settings.key.address

    @classmethod
    def balance(self) -> float:

        pprint(
            {'balance': float(provider.getbalance(Settings.key.address))}
            )

    def derive(self, key: str) -> str:
        '''derive a new address from <key>'''

        pprint(pa.Kutil(Settings.network, from_string=key).address)

    def random(self, n: int=1) -> list:
        '''generate <n> of random addresses, useful when testing'''

        rand_addr = [pa.Kutil(network=Settings.network).address for i in range(n)]

        pprint(rand_addr)

    def get_unspent(self, amount: int) -> Optional[dict]:
        '''quick find UTXO for this address'''

        try:
            pprint(
                {'UTXOs': provider.select_inputs(Settings.key.address, 0.02)['utxos'][0].__dict__['txid']}
                )
        except KeyError:
            pprint({'error': 'No UTXOs ;('})

    def new_privkey(self, key: str=None, backup: str=None, keyid: str=None, wif: bool=False, force: bool=False) -> str: ### NEW FEATURE ###
        '''import new private key, taking hex or wif format, or generate new key.
           You can assign a key name, otherwise it will become the main key.'''

        if wif:
            new_key = pa.Kutil(network=Settings.network, from_wif=key)
            key = new_key.privkey
        elif (not keyid) and key:
            new_key = pa.Kutil(network=Settings.network, privkey=bytearray.fromhex(key))

        set_new_key(new_key=key, backup_id=backup, key_id=keyid, force=force)

        if not keyid:
            if not new_key:
                new_key = pa.Kutil(network=Settings.network, privkey=bytearray.fromhex(load_key()))
            Settings.key = new_key

        return Settings.key.address # this still doesn't work properly

    def set_main(self, keyid: str, backup: str=None, force: bool=False) -> str: ### NEW FEATURE ###
        '''restores old key from backup and sets as personal address'''

        set_new_key(old_key_backup=keyid, backup_id=backup, force=force)
        Settings.key = pa.Kutil(network=Settings.network, privkey=bytearray.fromhex(load_key()))

        return Settings.key.address

    def show_stored(self, keyid: str, pubkey: bool=False, privkey: bool=False, wif: bool=False) -> str: ### NEW FEATURE ###
        '''shows stored alternative keys'''

        try:
            raw_key = bytearray.fromhex(get_key(keyid))
        except TypeError:
            exc_text = "No key data for key {}".format(keyid)
            raise Exception(exc_text)

        key = pa.Kutil(network=Settings.network, privkey=raw_key)

        if privkey:
             return key.privkey
        elif pubkey:
             return key.pubkey
        elif wif:
             return key.wif
        else:
             return key.address

    def show_all(self):
        keyids = du.get_all_keyids()
        print("Address".ljust(35), "Balance".ljust(15), "Keyid".ljust(15))
        print("---------------------------------------------------------")
        for raw_keyid in keyids:
            try:
                keyid = raw_keyid.replace("key_bak_", "")
                raw_key = bytearray.fromhex(get_key(keyid))
                key = pa.Kutil(network=Settings.network, privkey=raw_key)
                addr = key.address
                balance = str(provider.getbalance(addr))
                print(addr.ljust(35), balance.ljust(15), keyid.ljust(15))
                
                      
            except:
                continue

    def delete_key_from_keyring(self, keyid: str) -> None: ### NEW FEATURE ###
        '''deletes a key with an id. Cannot be used to delete main key.'''
        delete_key(keyid)

    def import_to_wallet(self, accountname: str, keyid: str=None) -> None: ### NEW FEATURE ###
        '''imports main key or any stored key to wallet managed by RPC node.
           TODO: should accountname be mandatory or not?'''
        if keyid:
            pkey = pa.Kutil(network=Settings.network, privkey=bytearray.fromhex(get_key(keyid)))
            wif = pkey.wif
        else:
            wif = Settings.wif
        provider.importprivkey(wif, account_name=accountname)

    def my_votes(self, deckid, address=Settings.key.address):
        '''shows votes cast from this address.'''
        return du.show_votes_by_address(provider, deckid, address)

    def my_donations(self, deckid, address=Settings.key.address):
        '''shows donation states involving this address.'''
        return du.show_donations_by_address(provider, deckid, address)
        

class Deck:

    @classmethod
    def list(self):
        '''find all valid decks and list them.'''

        decks = pa.find_all_valid_decks(provider, Settings.deck_version,
                                        Settings.production)

        print_deck_list(decks)

    @classmethod
    def find(self, key):
        '''
        Find specific deck by key, with key being:
        <id>, <name>, <issuer>, <issue_mode>, <number_of_decimals>
        '''

        decks = pa.find_all_valid_decks(provider,
                                        Settings.deck_version,
                                        Settings.production)
        print_deck_list(
            (d for d in decks if key in d.id or (key in d.to_json().values()))
            )

    @classmethod
    def info(self, deck_id):
        '''display deck info'''

        deck = pa.find_deck(provider, deck_id, Settings.deck_version,
                            Settings.production)
        print_deck_info(deck)

    @classmethod
    def p2th(self, deck_id: str) -> None:
        '''print out deck p2th'''

        pprint(pa.Kutil(network=Settings.network,
                        privkey=bytearray.fromhex(deck_id)).address)

    @classmethod
    def __new(self, name: str, number_of_decimals: int, issue_mode: int,
              asset_specific_data: str=None, locktime=None):
        '''create a new deck.'''

        network = Settings.network
        production = Settings.production
        version = Settings.deck_version

        new_deck = pa.Deck(name, number_of_decimals, issue_mode, network,
                           production, version, asset_specific_data)

        return new_deck

    @classmethod
    def spawn(self, verify: bool=False, sign: bool=False,
              send: bool=False, locktime: int=0, **kwargs) -> None:
        '''prepare deck spawn transaction'''

        deck = self.__new(**kwargs)

        spawn = pa.deck_spawn(provider=provider,
                              inputs=provider.select_inputs(Settings.key.address, 0.02),
                              deck=deck,
                              change_address=Settings.change,
                              locktime=locktime
                              )

        if verify:
            print(
                cointoolkit_verify(spawn.hexlify())
                 )  # link to cointoolkit - verify

        if sign:

            tx = signtx(spawn)

            if send:
                pprint({'txid': sendtx(tx)})

            return {'hex': tx.hexlify()}

        return spawn.hexlify()

    @classmethod
    def encode(self, json: bool=False, **kwargs) -> None:
        '''compose a new deck and print out the protobuf which
           is to be manually inserted in the OP_RETURN of the transaction.'''

        if json:
            pprint(self.__new(**kwargs).metainfo_to_dict)

        pprint({'hex': self.__new(**kwargs).metainfo_to_protobuf.hex()})

    @classmethod
    def decode(self, hex: str) -> None:
        '''decode deck protobuf'''

        script = NulldataScript.unhexlify(hex).decompile().split(' ')[1]

        pprint(parse_deckspawn_metainfo(bytes.fromhex(script),
                                        Settings.deck_version))

    def issue_modes(self):

        im = tuple({mode.name: mode.value} for mode_name, mode in pa.protocol.IssueMode.__members__.items())

        pprint(im)

    def my(self):
        '''list decks spawned from address I control'''

        self.find(Settings.key.address)

    def issue_mode_combo(self, *args: list) -> None:

        pprint(
            {'combo': functools.reduce(operator.or_, *args)
             })

    @classmethod
    def at_spawn_old(self, name, tracked_address, verify: bool=False, sign: bool=False,
              send: bool=False, locktime: int=0, multiplier=1, number_of_decimals=2, version=1) -> None: ### ADDRESSTRACK ###
        '''Wrapper to facilitate addresstrack spawns without having to deal with asset_specific_data.'''
        # TODO: format has changed
        if version == 0:
            asset_specific_data = b"trk:" + tracked_address.encode("utf-8") + b":" + str(multiplier).encode("utf-8")
        elif version == 1:
            b_identifier = b'AT'
            b_multiplier = multiplier.to_bytes(2, "big")
            b_address = tracked_address.encode("utf-8")
            asset_specific_data = b_identifier + b_multiplier + b_address

        return self.spawn(name=name, number_of_decimals=number_of_decimals, issue_mode=0x01, locktime=locktime,
                          asset_specific_data=asset_specific_data, verify=verify, sign=sign, send=send)


    @classmethod
    def dt_spawn(self, name: str, dp_length: int, dp_quantity: int, min_vote: int=0, sdp_periods: int=None, sdp_deck: str=None, verify: bool=False, sign: bool=False, send: bool=False, locktime: int=0, number_of_decimals=2) -> None: ### ADDRESSTRACK ###
        '''Wrapper to facilitate addresstrack DT spawns without having to deal with asset_specific_data.'''

        b_identifier = b'DT' #

        try:

            b_dp_length = dp_length.to_bytes(3, "big")
            b_dp_quantity = dp_quantity.to_bytes(2, "big")
            b_min_vote = min_vote.to_bytes(1, "big")

            if sdp_periods:
                b_sdp_periods = sdp_periods.to_bytes(1, "big")
                #b_sdp_deck = sdp_deck.to_bytes(32, "big")
                b_sdp_deck = bytearray.fromhex(sdp_deck)
                print(b_sdp_deck)
            else:
                b_sdp_periods, b_sdp_deck = b'', b''

        except OverflowError:
            raise ValueError("Deck spawn: at least one parameter overflowed.")

        asset_specific_data = b_identifier + b_dp_length + b_dp_quantity + b_min_vote + b_sdp_periods + b_sdp_deck

        print("asset specific data:", asset_specific_data)

        return self.spawn(name=name, number_of_decimals=number_of_decimals, issue_mode=0x01, locktime=locktime,
                          asset_specific_data=asset_specific_data, verify=verify, sign=sign, send=send)

    def dt_init(self, deckid: str):
        '''Intializes deck and imports all P2TH addresses into node.'''

        du.init_dt_deck(provider, Settings.network, deckid) 

    @classmethod
    def dt_list(self):
        '''
        List all DT decks.
        '''
        # TODO: This does not catch some errors with invalid decks which are displayed:
        # InvalidDeckSpawn ("InvalidDeck P2TH.") -> not catched in deck_parser in pautils.py
        # 'error': 'OP_RETURN not found.' -> InvalidNulldataOutput , in pautils.py
        # 'error': 'Deck () metainfo incomplete, deck must have a name.' -> also in pautils.py, defined in exceptions.py.

        decks = pa.find_all_valid_decks(provider,
                                        Settings.deck_version,
                                        Settings.production)
        dt_decklist = []
        for d in decks:
            try:
                if d.at_type == "DT":
                    dt_decklist.append(d)
            except AttributeError:
                continue

        print_deck_list(dt_decklist)


class Card:

    '''card information and manipulation'''

    @classmethod
    def __find_deck(self, deckid) -> Deck:

        deck = pa.find_deck(provider, deckid,
                            Settings.deck_version,
                            Settings.production)

        if deck:
            return deck

    @classmethod
    def __list(self, deckid: str):

        deck = self.__find_deck(deckid)

        try:
            cards = pa.find_all_valid_cards(provider, deck)
        except pa.exceptions.EmptyP2THDirectory as err:
            return err

        return {'cards': list(cards),
                'deck': deck}

    @classmethod
    def list(self, deckid: str):
        '''list the valid cards on this deck'''

        cards = self.__list(deckid)['cards']

        print_card_list(cards)

    def balances(self, deckid: str):
        '''list card balances on this deck'''

        cards, deck = self.__list(deckid).values()

        state = pa.protocol.DeckState(cards)

        balances = [exponent_to_amount(i, deck.number_of_decimals)
                    for i in state.balances.values()]

        pprint(dict(zip(state.balances.keys(), balances)))

    def checksum(self, deckid: str) -> bool:
        '''show deck card checksum'''

        cards, deck = self.__list(deckid).values()

        state = pa.protocol.DeckState(cards)

        pprint({'checksum': state.checksum})

    @staticmethod
    def to_exponent(number_of_decimals, amount):
        '''convert float to exponent'''

        return amount_to_exponent(amount, number_of_decimals)

    @classmethod
    def __new(self, deckid: str, receiver: list=None,
              amount: list=None, asset_specific_data: str=None) -> pa.CardTransfer:
        '''fabricate a new card transaction
        * deck_id - deck in question
        * receiver - list of receivers
        * amount - list of amounts to be sent, must be float
        '''

        deck = self.__find_deck(deckid)

        if isinstance(deck, pa.Deck):
            card = pa.CardTransfer(deck=deck,
                                   receiver=receiver,
                                   amount=[self.to_exponent(deck.number_of_decimals, i)
                                           for i in amount],
                                   version=deck.version,
                                   asset_specific_data=asset_specific_data
                                   )

            return card

        raise Exception({"error": "Deck {deckid} not found.".format(deckid=deckid)})

    @classmethod
    def transfer(self, deckid: str, receiver: list=None, amount: list=None,
                 asset_specific_data: str=None,
                 locktime: int=0, verify: bool=False,
                 sign: bool=False, send: bool=False) -> Optional[dict]:
        '''prepare CardTransfer transaction'''

        print(deckid, receiver, amount)

        card = self.__new(deckid, receiver, amount, asset_specific_data)

        issue = pa.card_transfer(provider=provider,
                                 inputs=provider.select_inputs(Settings.key.address, 0.02),
                                 card=card,
                                 change_address=Settings.change,
                                 locktime=locktime
                                 )

        if verify:
            return cointoolkit_verify(issue.hexlify())  # link to cointoolkit - verify

        if sign:

            tx = signtx(issue)

            if send:
                pprint({'txid': sendtx(tx)})

            pprint({'hex': tx.hexlify()})

        return issue.hexlify()

    @classmethod
    def burn(self, deckid: str, receiver: list=None, amount: list=None,
             asset_specific_data: str=None,
             locktime: int=0, verify: bool=False, sign: bool=False) -> str:
        '''wrapper around self.transfer'''

        return self.transfer(deckid, receiver, amount, asset_specific_data,
                             locktime, verify, sign)

    @classmethod
    def issue(self, deckid: str, receiver: list=None, amount: list=None,
              asset_specific_data: str=None,
              locktime: int=0, verify: bool=False,
              sign: bool=False,
              send: bool=False) -> str:
        '''Wrapper around self.transfer'''

        return self.transfer(deckid, receiver, amount, asset_specific_data,
                             locktime, verify, sign, send)

    @classmethod
    def encode(self, deckid: str, receiver: list=None, amount: list=None,
               asset_specific_data: str=None, json: bool=False) -> str:
        '''compose a new card and print out the protobuf which
           is to be manually inserted in the OP_RETURN of the transaction.'''

        card = self.__new(deckid, receiver, amount, asset_specific_data)

        if json:
            pprint(card.metainfo_to_dict)

        pprint({'hex': card.metainfo_to_protobuf.hex()})

    @classmethod
    def decode(self, hex: str) -> dict:
        '''decode card protobuf'''

        script = NulldataScript.unhexlify(hex).decompile().split(' ')[1]

        pprint(parse_card_transfer_metainfo(bytes.fromhex(script),
                                            Settings.deck_version)
               )

    @classmethod
    def simulate_issue(self, deckid: str=None, ncards: int=10,
                       verify: bool=False,
                       sign: str=False, send: bool=False) -> str:
        '''create a batch of simulated CardIssues on this deck'''

        receiver = [pa.Kutil(network=Settings.network).address for i in range(ncards)]
        amount = [random.randint(1, 100) for i in range(ncards)]

        return self.transfer(deckid=deckid, receiver=receiver, amount=amount,
                             verify=verify, sign=sign, send=send)

    def export(self, deckid: str, filename: str):
        '''export cards to csv'''

        cards = self.__list(deckid)['cards']
        export_to_csv(cards=list(cards), filename=filename)

    def parse(self, deckid: str, cardid: str) -> None:
        '''parse card from txid and print data'''

        deck = self.__find_deck(deckid)
        cards = list(get_card_transfer(provider, deck, cardid))

        for i in cards:
            pprint(i.to_json())

    @classmethod
    def __find_deck_data(self, deckid: str) -> tuple: ### NEW FEATURE - AT ###
        '''returns addresstrack-specific data'''

        deck = self.__find_deck(deckid)

        try:
            tracked_address, multiplier = deck.asset_specific_data.split(b":")[1:3]
        except IndexError:
            raise Exception("Deck has not the correct format for address tracking.")

        return tracked_address.decode("utf-8"), int(multiplier)

    @classmethod ### NEW FEATURE - AT ###
    def at_issue(self, deckid: str, txid: str, receiver: list=None, amount: list=None,
              locktime: int=0, verify: bool=False, sign: bool=False, send: bool=False, force: bool=False) -> str:
        '''To simplify self.issue, all data is taken from the transaction.'''

        tracked_address, multiplier = self.__find_deck_data(deckid)
        spending_tx = provider.getrawtransaction(txid, 1)

        for output in spending_tx["vout"]:
            if tracked_address in output["scriptPubKey"]["addresses"]:
                vout = str(output["n"]).encode("utf-8")
                spent_amount = output["value"] * multiplier
                break
        else:
            raise Exception("No vout of this transaction spends to the tracked address")

        if not receiver: # if there is no receiver, spends to himself.
            receiver = [Settings.key.address]

        if not amount:
            amount = [spent_amount]

        if (sum(amount) != spent_amount) and (not force):
            raise Exception("Amount of cards does not correspond to the spent coins. Use --force to override.")

        # TODO: for now, hardcoded asset data; should be a pa function call
        asset_specific_data = b"tx:" + txid.encode("utf-8") + b":" + vout 


        return self.transfer(deckid=deckid, receiver=receiver, amount=amount, asset_specific_data=asset_specific_data,
                             verify=verify, locktime=locktime, sign=sign, send=send)

    @classmethod ### NEW FEATURE - DT ###
    def dt_issue(self, deckid: str, donation_txid: str, amount: list, donation_vout: int=2, move_txid: str=None, receiver: list=None, locktime: int=0, verify: bool=False, sign: bool=False, send: bool=False, force: bool=False) -> str:
        '''To simplify self.issue, all data is taken from the transaction.'''
        # TODO: Multiplier must be replaced by the max epoch amount!

        deck = self.__find_deck(deckid)
        # multiplier = int.from_bytes(deck.asset_specific_data[2:4], "big") # TODO: hardcoded for now! Take into account that the id bytes (now 2) are considered to be changed to 1.
        spending_tx = provider.getrawtransaction(donation_txid, 1)
        # print(multiplier)

        try:
            spent_amount = spending_tx["vout"][donation_vout]["value"]
        except (IndexError, KeyError):
            raise Exception("No vout of this transaction spends to the tracked address")

        # TODO: this must be changed completely. Multiplier is irrelevant, but we would need the slot data to calculate the amount automatically. Maybe make amount mandatory and throw out the whole part until we have an interface for slots.
        # max_amount = spent_amount * multiplier

        if not receiver: # if there is no receiver, spends to himself.
            receiver = [Settings.key.address]

        #if not amount:
        #    amount = [max_amount]

        #elif (sum(amount) != max_amount) and (not force):
        #    raise Exception("Amount of cards does not correspond to the spent coins. Use --force to override.")

        # TODO: for now, hardcoded asset data; should be a ppa function call
        b_id = b'DT'
        b_donation_txid = bytes.fromhex(donation_txid)
        b_vout = int.to_bytes(donation_vout, 1, "big")
        b_move_txid = bytes.fromhex(move_txid) if move_txid else b''
        asset_specific_data = b_id + b_donation_txid + b_vout + b_move_txid

        print("ASD", asset_specific_data)


        return self.transfer(deckid=deckid, receiver=receiver, amount=amount, asset_specific_data=asset_specific_data,
                             verify=verify, locktime=locktime, sign=sign, send=send)


    #@classmethod
    #def at_issue_all(self, deckid: str) -> str:
    #    '''this function checks all transactions from own address to tracked address and then issues tx.'''
    #
    #    deck = self.__find_deck(deckid)
    #    tracked_address = deck.asset_specific_data.split(b":")[1].decode("utf-8")
    #     # UNFINISHED #

class Transaction:

    def raw(self, txid: str) -> None:
        '''fetch raw tx and display it'''

        tx = provider.getrawtransaction(txid, 1)

        pprint(json.dumps(tx, indent=4))

    def sendraw(self, rawtx: str) -> None:
        '''sendrawtransaction, returns the txid'''

        txid = provider.sendrawtransaction(rawtx)

        pprint({'txid': txid})

    def dt_create_proposal(self, deckid: str, req_amount: str, periods: int, slot_allocation_duration: int, change_address: str=None, tx_fee: str="0.01", p2th_fee: str="0.01", input_txid: str=None, input_vout: int=None, input_address: str=Settings.key.address, first_ptx: str=None, sign: bool=False, send: bool=False, verify: bool=False):

        #if input_address is None:
        #    input_address = Settings.address

        params = { "id" : "DP" , "dck" : deckid, "eps" : int(periods), "sla" : int(slot_allocation_duration), "amt" : int(req_amount), "ptx" : first_ptx}

        rawtx = du.create_unsigned_trackedtx(provider, "proposal", params, deckid=deckid, change_address=change_address, input_address=input_address, raw_tx_fee=tx_fee, raw_p2th_fee=p2th_fee)

        return du.finalize_tx(rawtx, verify, sign, send)


    def dt_signal_funds(self, proposal_txid: str, amount: str, dest_address: str, change_address: str=None, tx_fee: str="0.01", p2th_fee: str="0.01", sign: bool=False, send: bool=False, verify: bool=False, check_round: int=None, wait: bool=False, input_address: str=Settings.key.address) -> None:
        '''this creates a compliant signalling transaction.'''

        if check_round is not None:
            if not du.check_current_period(provider, proposal_txid, "signalling", dist_round=check_round, wait=wait):
                return

        params = { "id" : "DS" , "prp" : proposal_txid }

        rawtx = du.create_unsigned_trackedtx(provider, "signalling", params, change_address=change_address, dest_address=dest_address, input_address=input_address, raw_tx_fee=tx_fee, raw_p2th_fee=p2th_fee, raw_amount=amount)

        return du.finalize_tx(rawtx, verify, sign, send)

    def dt_lock_funds(self, proposal_txid: str, raw_amount: str, dest_address: str, change_address: str=None, tx_fee: str="0.01", p2th_fee: str="0.01", input_address: str=Settings.key.address, sign: bool=False, send: bool=False, verify: bool=False, check_round: int=None, wait: bool=False, use_slot: bool=True, new_inputs: bool=False, dist_round: int=None, debug: bool=False) -> None: ### ADDRESSTRACK ###

        if check_round is not None:
            dist_round=check_round
            if not du.check_current_period(provider, proposal_txid, "locking", dist_round=check_round, wait=wait):
                return

        params = { "id" : "DL" , "prp" : proposal_txid }

        cltv_timelock = du.calculate_timelock(provider, proposal_txid)
        print("Locking funds until block", cltv_timelock)

        rawtx = du.create_unsigned_trackedtx(provider, "locking", params, dest_address=dest_address, change_address=change_address, input_address=input_address, raw_tx_fee=tx_fee, raw_p2th_fee=p2th_fee, cltv_timelock=cltv_timelock, use_slot=use_slot, new_inputs=new_inputs, dist_round=dist_round, debug=debug)
        
        return du.finalize_tx(rawtx, verify, sign, send)


    def dt_donate_funds(self, proposal_txid: str, raw_amount: str, change_address: str=None, tx_fee: str="0.01", p2th_fee: str="0.01", sign: bool=False, input_address: str=Settings.key.address, send: bool=False, check_round: int=None, wait: bool=False, use_slot: bool=True, new_inputs: bool=False) -> None: ### ADDRESSTRACK ###

        if check_round is not None:
            if not du.check_current_period(provider, proposal_txid, "donation", dist_round=check_round, wait=wait):
                return

        params = { "id" : "DD" , "prp" : proposal_txid }

        rawtx = du.create_unsigned_trackedtx(provider, "donation", params, change_address=change_address, input_address=input_address, raw_tx_fee=tx_fee, raw_p2th_fee=p2th_fee, use_slot=use_slot, new_inputs=new_inputs)
        
        return du.finalize_tx(rawtx, verify, sign, send)

    def dt_vote(self, proposal_id: str, vote: str, p2th_fee: str="0.01", tx_fee: str="0.01", change_address: str=None, input_address: str=Settings.key.address, verify: bool=False, sign: bool=False, send: bool=False, check_phase: int=None, wait: bool=False, confirm: bool=True):

        if check_phase is not None:
            print("Checking blockheights of phase", check_phase, "...")
            if not du.check_current_period(provider, proposal_id, "voting", phase=check_phase, wait=wait):
                return

        if vote in ("+", "positive", "p", "1", "yes", "y", "true"):
            votechar = "+"
        elif vote in ("-", "negative", "n", "0", "no", "n", "false"):
            votechar = "-"
        else:
            raise ValueError("Incorrect vote. Vote with 'positive'/'yes' or 'negative'/'no'.")

        vote_readable = "Positive" if votechar == "+" else "Negative" 
        print("Vote:", vote_readable ,"\nProposal ID:", proposal_id)

        params = { "id" : "DV" , "prp" : proposal_id, "vot" : votechar }

        rawtx = du.create_unsigned_trackedtx(provider, "voting", params, change_address=change_address, input_address=input_address, raw_tx_fee=tx_fee, raw_p2th_fee=p2th_fee)

        console_output = du.finalize_tx(rawtx, verify, sign, send)

        if confirm and sign and send:
            print("Waiting for confirmation (this can take several minutes) ...", end='')
            confirmations = 0
            while confirmations == 0:
                tx = provider.getrawtransaction(rawtx.txid, 1)
                try:
                    confirmations = tx["confirmations"]
                    break
                except KeyError:
                    du.spinner(10)

            print("\nVote confirmed.")

        return console_output
               
class Proposal: ### DT ###

    def get_votes(self, proposal_txid: str, phase: int=0, debug: bool=False):

        votes = get_votestate(provider, proposal_txid, phase, debug)

        pprint("Positive votes (weighted): " + str(votes["positive"]))
        pprint("Negative votes (weighted): " + str(votes["negative"]))

        approval_state = "approved." if votes["positive"] > votes["negative"] else "not approved."
        pprint("In this round, the proposal was " + approval_state)

    def current_period(self, proposal_txid: str, blockheight: int=None):

        period = du.get_period(provider, proposal_txid, blockheight)
        pprint(du.printout_period(period))

    def list(self, deckid: str, block: int=None, show_completed: bool=False) -> None:
        '''Shows all proposals and the period they are currently in, optionally at a specific blockheight.'''

        # TODO: Abandoned and completed proposals cannot be separated this way, this needs a more complex
        #       method involving the parser. => Advanced mode could be a good idea.
        # TODO: deck e9742552e3607754b1c17b28421061211317428c83c299f3cbe2d2cc62e49fa4 raises an error, it seems
        # the deck tx is not well formatted, but should be catched in some way.
        # TODO: Non-DT decks like e282a8d4db32e302496ae222172ff6cce12150338686ec00b75c967e44a833d3 simply show "No proposals found." They should be differetiated.
        # TODO: Printout should be reorganized, so two proposals which overlap by coincidence don't share erroneously the same block heights for start and end.
        try:
            pstate_periods = du.get_proposal_state_periods(provider, deckid, block)
        except KeyError:
            pprint("Error, unconfirmed proposals in mempool. Wait until they are confirmed.")
            return

        excluded_list = []
        #if show_completed:
        #    statelist.append("completed")
        #if show_abandoned:
        #    statelist.append("abandoned")

        if len([p for l in pstate_periods.values() for p in l]) == 0:
            print("No proposals found for deck: " + deckid)
        else:
            print("Proposals in the following periods are available for this deck:")

        for state in pstate_periods:
            if state not in excluded_list and (len(pstate_periods[state]) > 0):
                print("* " + du.printout_period(state, show_blockheights=True))
                print("** ", end='')
                print("\n** ".join(pstate_periods[state]))

    def info(self, proposal_txid):
        info = du.get_proposal_info(provider, proposal_txid)
        pprint(info)

    def show_state(self, proposal_txid, debug=False):
        pstate = get_proposal_state(provider, proposal_txid, phase=0, debug=debug)
        pprint(pstate.__dict__)

    def show_donation_states(self, proposal_id: str, address: str=Settings.key.address, debug=False):
        dstates = du.get_donation_states(provider, proposal_id, address=address, debug=debug)
        for dstate in dstates:
            pprint("Donation state ID: " + dstate.id)
            #pprint(dstate.__dict__)
            ds_dict = dstate.__dict__
            for item in ds_dict:
                print(item + ":", ds_dict[item])

    def show_all_donation_states(self, proposal_id: str, debug=False):
        dstates = du.get_donation_states(provider, proposal_id, debug=debug)
        for dstate in dstates:
            pprint("Donation state ID: " + dstate.id)

            ds_dict = dstate.__dict__
            for item in ds_dict:
                print(item + ":", ds_dict[item])


def main():

    init_keystore()

    fire.Fire({
        'config': Config(),
        'deck': Deck(),
        'card': Card(),
        'address': Address(),
        'transaction': Transaction(),
        'coin': Coin(),
        'proposal' : Proposal()
        })


if __name__ == '__main__':
    main()

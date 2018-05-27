import fire
import random
import pypeerassets as pa
from pacli.provider import provider
from pacli.config import Settings
from pacli.keystore import init_keystore
from pacli.tui import print_deck_info, print_deck_list
from pacli.tui import print_card_list
from btcpy.structs.script import NulldataScript
import json


def cointoolkit_verify(hex: str) -> str:
    '''tailor cointoolkit verify URL'''

    base_url = 'https://indiciumfund.github.io/cointoolkit/'
    if provider.network == "peercoin-testnet":
        mode = "mode=peercoin_testnet"
    if provider.network == "peercoin":
        mode = "mode=peercoin"

    return base_url + "?" + mode + "&" + "verify=" + hex


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

        return float(provider.getbalance(Settings.key.address))

    def derive(self, key: str) -> str:
        '''derive a new address from <key>'''

        return pa.Kutil(Settings.network, from_string=key).address

    def random(self, n: int=1) -> list:
        '''generate <n> of random addresses, useful when testing'''

        return [pa.Kutil(network=Settings.network).address for i in range(n)]

    def get_unspent(self, amount: int) -> str:
        '''quick find UTXO for this address'''

        try:
            return provider.select_inputs(Settings.key.address, 0.02)['utxos'][0].__dict__['txid']
        except KeyError:
            print({'error': 'No UTXOs ;('})


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
            (d for d in decks if key in d.id or (key in d.__dict__.values()))
            )

    @classmethod
    def info(self, deck_id):
        '''display deck info'''

        deck = pa.find_deck(provider, deck_id, Settings.deck_version,
                            Settings.production)
        print_deck_info(deck)

    @classmethod
    def __new(self, name: str, number_of_decimals: int, issue_mode: int,
              asset_specific_data: str=None):
        '''create a new deck.'''

        network = Settings.network
        production = Settings.production
        version = Settings.deck_version

        new_deck = pa.Deck(name, number_of_decimals, issue_mode, network,
                           production, version, asset_specific_data)

        return new_deck

    @classmethod
    def spawn(self, verify=False, **kwargs):
        '''prepare deck spawn transaction'''

        deck = self.__new(**kwargs)

        spawn = pa.deck_spawn(provider=provider,
                              inputs=provider.select_inputs(Settings.key.address, 0.02),
                              deck=deck,
                              change_address=Settings.change
                              )

        if verify:
            return cointoolkit_verify(spawn.hexlify())  # link to cointoolkit - verify

        return spawn.hexlify()

    @classmethod
    def encode(self, json: bool=False, **kwargs) -> str:
        '''compose a new deck and print out the protobuf which
           is to be manually inserted in the OP_RETURN of the transaction.'''

        if json:
            return self.__new(**kwargs).metainfo_to_dict

        return self.__new(**kwargs).metainfo_to_protobuf.hex()

    @classmethod
    def decode(self, hex: str) -> dict:
        '''decode deck protobuf'''

        script = NulldataScript.unhexlify(hex).decompile().split(' ')[1]

        return pa.parse_deckspawn_metainfo(bytes.fromhex(script), Settings.deck_version)

    def issue_modes(self):

        im = tuple({mode.name: mode.value} for mode_name, mode in pa.IssueMode.__members__.items())

        print(json.dumps(im, indent=1, sort_keys=True))

    def checksum(self, deck_id: str) -> bool:
        '''check if deck balances are in order'''

        raise NotImplementedError

    def my(self):
        '''list decks spawned from address I control'''

        return self.find(Settings.key.address)


class Card:

    '''card information and manipulation'''

    @classmethod
    def list(self, deckid: str):
        '''list the valid cards on this deck'''

        deck = pa.find_deck(provider, deckid,
                            Settings.deck_version,
                            Settings.production)

        try:
            cards = list(pa.find_all_valid_cards(provider, deck))
            print_card_list(cards)
        except pa.exceptions.EmptyP2THDirectory as err:
            return err

    def balances(self, deckid):
        '''list card balances on this deck'''
        raise NotImplementedError

    @staticmethod
    def to_exponent(number_of_decimals, amount):
        '''convert float to exponent'''

        return pa.amount_to_exponent(amount, number_of_decimals)

    @classmethod
    def __new(self, deckid: str, receiver: list=None,
              amount: list=None, asset_specific_data: str=None) -> pa.CardTransfer:
        '''fabricate a new card transaction
        * deck_id - deck in question
        * receiver - list of receivers
        * amount - list of amounts to be sent, must be float
        '''

        production = Settings.production
        version = Settings.deck_version
        deck = pa.find_deck(provider, deckid, version, production)

        card = pa.CardTransfer(deck, receiver,
                               [self.to_exponent(deck.number_of_decimals, i) for i in amount],
                               version, asset_specific_data)

        return card

    @classmethod
    def transfer(self, deckid: str, receiver: list=None, amount: list=None,
                 asset_specific_data: str=None, verify=False) -> str:
        '''prepare CardTransfer transaction'''

        card = self.__new(deckid, receiver, amount, asset_specific_data)

        issue = pa.card_transfer(provider=provider,
                                 inputs=provider.select_inputs(Settings.key.address, 0.02),
                                 card=card,
                                 change_address=Settings.change
                                 )

        if verify:
            return cointoolkit_verify(issue.hexlify())  # link to cointoolkit - verify

        return issue.hexlify()

    @classmethod
    def burn(self, deckid: str, receiver: list=None, amount: list=None,
             asset_specific_data: str=None, verify=False) -> str:
        '''wrapper around self.transfer'''

        return self.transfer(deckid, receiver, amount, asset_specific_data, verify)

    @classmethod
    def issue(self, deckid: str, receiver: list=None, amount: list=None,
              asset_specific_data: str=None, verify=False) -> str:
        '''Wrapper around self.tranfer'''

        return self.transfer(deckid, receiver, amount, asset_specific_data, verify)


    @classmethod
    def encode(self, deckid: str, receiver: list=None, amount: list=None,
               asset_specific_data: str=None, json: bool=False) -> str:
        '''compose a new card and print out the protobuf which
           is to be manually inserted in the OP_RETURN of the transaction.'''

        card = self.__new(deckid, receiver, amount, asset_specific_data)

        if json:
            return card.metainfo_to_dict

        return card.metainfo_to_protobuf.hex()

    @classmethod
    def decode(self, hex: str) -> dict:
        '''decode card protobuf'''

        script = NulldataScript.unhexlify(hex).decompile().split(' ')[1]

        return pa.parse_card_transfer_metainfo(bytes.fromhex(script),
                                               Settings.deck_version)

    def simulate_issue(self, deckid: str=None, ncards: int=10, verify=False) -> str:
        '''create a batch of simulated CardIssues on this deck'''

        receiver = [pa.Kutil(network='tppc').address for i in range(ncards)]
        amount = [random.randint(1, 100) for i in range(ncards)]

        return self.issue(deckid, receiver, amount, verify)


class Transaction:

    def raw(self, txid):
        '''fetch raw tx and display it'''

        tx = provider.getrawtransaction(txid, 1)

        print(json.dumps(tx, indent=4))


def main():

    init_keystore()

    fire.Fire({
        'deck': Deck(),
        'card': Card(),
        'address': Address(),
        'transaction': Transaction()
        })


if __name__ == '__main__':
    main()

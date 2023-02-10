# Coin Tracing Scripts

You need a synced full node available on the same machine that you are running these scripts from

## Install

```shell
python3 -m venv venv
. ./venv/bin/activate
pip install chia-blockchain==1.6.2
```

## Use

```shell
. ./venv/bin/activate
python prefarm-coins.py

python children.py 0x1fd60c070e821d785b65e10e5135e52d12c8f4d902a506f48bc1c5268b7bb45b

python lineage.py  0xd7a81eece6b0450c9eaf3b3a9cdbff5bde0f1e51f1f18fcf50cc533296cb04b6
```

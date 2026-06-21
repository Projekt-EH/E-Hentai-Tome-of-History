# E-Hentai Comment Crawler

## Run

```shell
python __init__.py
```

or

```shell
python __init__.py -p <parallel_workers>
```

The argument "parallel_workers" sets the number of parallel threads in
uploader/listing URL crawling.

The maximum number allowed is 20.

## Config

The config file looks like this:

```json
{
  "igneous": "mystery",
  "ipb_member_id": "0",
  "ipb_pass_hash": "0",
  "nw":"1",
  "hath_perks":"",
  "star":""
}
```

You can modify it to match with your settings.

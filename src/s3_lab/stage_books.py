#!/usr/bin/env python3

import json
import logging
import os
import sys
import time

import boto3
import requests
from botocore.exceptions import ClientError

# logger
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
log = logging.getLogger(__name__)

s3 = boto3.client("s3", region_name="us-east-1")

def parse_args():
    """Read three command line arguments.

    Returns:
         (list_file, index_path, bucket), all strings.
    """
    # sys.argv[0] is the script name, so we need at least 4 entries
    if len(sys.argv) < 4:
        log.error("Usage: python stage_books.py <list_file> <index_path> <bucket>")
        log.error("Example: python stage_books.py book_urls.txt index.html public-mst3k")
        sys.exit(1)

    list_file = sys.argv[1]    # path of the book list (book_urls.txt)
    index_path = sys.argv[2]   # path of the index page (index.html)
    bucket = sys.argv[3]       # bucket name (public-mst3k)

    log.info(f"Book list: {list_file}, index page: {index_path}, bucket: {bucket}")
    return list_file, index_path, bucket

def download_books(list_file, dest_dir):
    """Download books listed in list_file into dest_dir

    Args:
        list_file: path of the book list, one URL per line.
        dest_dir: folder for saving the books in.

    Returns:
        list: local paths of the books, e.g. ["books/pg11.txt", ...].
    """
    # Like mkdir -p: no error if the folder already exists
    os.makedirs(dest_dir, exist_ok=True)

    # Read the URLs, skip blank lines
    with open(list_file) as f:
        urls = [line.strip() for line in f if line.strip()]
    log.info(f"Found {len(urls)} URLs in {list_file}")

    paths = []
    for url in urls:
        # Last part of the URL is the file name: pg1342.txt
        filename = url.split("/")[-1]
        path = os.path.join(dest_dir, filename)

        # Already downloaded on a previous run: skip, but still keep it
        if os.path.exists(path):
            log.info(f"Skipping {path}, already exists")
            paths.append(path)
            continue

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()  # error for 404
            with open(path, "wb") as out:
                out.write(response.content)
            log.info(f"Downloaded {url} -> {path}")
            paths.append(path)
        except requests.RequestException as e:
            log.error(f"Error downloading {url}: {e}")

        # avoid bombarding servers
        time.sleep(1)

    log.info(f"{len(paths)} of {len(urls)} books ready in {dest_dir}")
    return paths

def create_bucket(bucket):
    """Create bucket if does not already exist.

    Args:
        bucket: the bucket name.

    Returns:
        bool: True if the bucket exists aferwards, false otherwise.
    """
    # Check first: creating a bucket you already own raises an error
    try:
        s3.head_bucket(Bucket=bucket)
        log.info(f"Bucket {bucket} already exists")
        return True
    except ClientError:
        log.info(f"Bucket {bucket} not found, creating it")

    # Not found (or not accessible): try to create it
    try:
        s3.create_bucket(Bucket=bucket)
        log.info(f"Created bucket {bucket}")
        return True
    except ClientError as e:
        log.error(f"Error creating bucket {bucket}: {e}")
        return False

def make_public(bucket):
    """Make bucket's objects publicly readable.

    Turns off Block Public Access, attaches bucket policy-
    lets anyone read (GetObject).

    Args:
        bucket: bucket name

    Returns:
        bool: True if success, False else.
    """
    try:
        # turn off Block Public Access for bucket.
        s3.put_public_access_block(
            Bucket=bucket,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": False,
                "IgnorePublicAcls": False,
                "BlockPublicPolicy": False,
                "RestrictPublicBuckets": False,
            },
        )
        log.info(f"Turned off Block Public Access for {bucket}")

        # build the bucket policy - py dictionary 
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": "s3:GetObject",
                    "Resource": f"arn:aws:s3:::{bucket}/*",
                }
            ],
        }

        #  attach it
        s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps(policy))
        log.info(f"Attached public-read policy to {bucket}")
        return True
    except ClientError as e:
        log.error(f"Error making bucket {bucket} public: {e}")
        return False

def upload_files(bucket, file_paths):
    """Upload the downloaded books to the top level of the bucket.

    Args:
        bucket: bucket name.
        file_paths: local paths returned by download_books.

    Returns:
        int: number of files uploaded successfully.
    """
    count = 0
    for path in file_paths:
        # Key is the file name only: books/pg1342.txt -> pg1342.txt
        key = os.path.basename(path)
        try:
            with open(path, "rb") as f:
                s3.put_object(
                    Bucket=bucket,
                    Key=key,
                    Body=f,
                    ContentType="text/plain; charset=utf-8",
                )
            log.info(f"Uploaded {path} to s3://{bucket}/{key}")
            count += 1
        except (ClientError, OSError) as e:
            log.error(f"Error uploading {path}: {e}")

    log.info(f"Uploaded {count} of {len(file_paths)} files")
    return count

def upload_index(bucket, index_path):
    """Upload the index page to bucket as index.html.

    Args:
        bucket: bucket name.
        index_path: local path of  index page.

    Returns:
        bool: True if success, False else.
    """
    try:
        with open(index_path, "rb") as f:
            s3.put_object(
                Bucket=bucket,
                Key="index.html",
                Body=f,
                ContentType="text/html",  # display it as a page
            )
        log.info(f"Uploaded {index_path} to s3://{bucket}/index.html")
        return True
    except FileNotFoundError:
        log.error(f"Local file not found: {index_path}")
        return False
    except ClientError as e:
        log.error(f"Error uploading index page: {e}")
        return False

def main():
    """Download books, make public bucket, upload everything."""
    list_file, index_path, bucket = parse_args()

    # Download the books; stop if nothing to upload
    paths = download_books(list_file, "books")
    if not paths:
        log.error("No books were downloaded, stopping")
        sys.exit(1)

    # make the bucket. stop if doesn't exist after
    if not create_bucket(bucket):
        log.error(f"Could not create bucket {bucket}, stopping")
        sys.exit(1)

    # public; stop on failure
    if not make_public(bucket):
        log.error(f"Could not make bucket {bucket} public, stopping")
        sys.exit(1)

    #Upload books and index page
    uploaded = upload_files(bucket, paths)
    index_ok = upload_index(bucket, index_path)

    #  Report result and  URL
    if uploaded == len(paths) and index_ok:
        log.info(f"Success: uploaded {uploaded} books and the index page")
    else:
        log.error(
            f"Finished with problems: uploaded {uploaded} of {len(paths)} "
            f"books, index page uploaded: {index_ok}"
        )
    log.info(f"Index page: https://{bucket}.s3.amazonaws.com/index.html")


if __name__ == "__main__":
    main()
#!/bin/bash
set -euo pipefail

if [ "$#" -lt 3 ]; then
    echo "Usage: $0 <book_url> <bucket> <expires_in_seconds>" >&2
    echo "Example: $0 https://www.gutenberg.org/cache/epub/1342/pg1342.txt secret-vdv9yr 3600"
    exit 1
fi

#name args
URL="$1"
BUCKET="$2"
EXPIRES="$3"

#save filename from URL
FILE="${URL##*/}"

#download into books 
mkdir -p books
curl -fsSL -o "books/$FILE" "$URL"
echo "Downloaded $URL to books/$FILE"
##poten flag with curl -kfL "$URL" -o "books/$FILENAME"

#create bucket if doesn't exist
if aws s3 ls "s3://$BUCKET" > /dev/null 2>&1; then
    echo "Bucket $BUCKET already exists"
else
    aws s3 mb "s3://$BUCKET"
fi

#upload book (priv) w/ content type for browser display
aws s3 cp "books/$FILE" "s3://$BUCKET/$FILE" --content-type "text/pain; charset=utf-8"  #is this spelled right?

# presigned url - for temp access to priv obj
echo "Presigned URL, valid for $EXPIRES seconds:"
aws s3 presign "s3://$BUCKET/$FILE" --expires-in "$EXPIRES"




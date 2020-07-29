"""
Define the web application's relative routes and the business logic for each
"""

import os
import sys
from pathlib import Path
from io import BytesIO
from datetime import datetime
from flask import render_template, flash, request, send_file
from werkzeug.utils import secure_filename
from pygate_grpc.client import PowerGateClient
from pygate_grpc.ffs import get_file_bytes, bytes_to_chunks, chunks_to_bytes
from pygate import app, db
from pygate.models import Files, Ffs


@app.route("/", methods=["GET"])
@app.route("/files", methods=["GET", "POST"])
def files():
    """
    Upload a new file to add to Filecoin via Powergate FFS and
    list files previously added. Allow users to download files from
    Filecoin via this list.
    """

    # Uploading a new file
    if request.method == "POST":

        # Use the default upload directory configured for the app
        upload_path = app.config["UPLOADDIR"]
        if not os.path.exists(upload_path):
            os.makedirs(upload_path)
        # Get the file and filename from the request
        upload = request.files["uploadfile"]
        file_name = secure_filename(upload.filename)

        try:
            # Save the uploaded file
            upload.save(os.path.join(upload_path, file_name))
        except:
            # Respond if the user did not provide a file to upload
            stored_files = Files.query.all()
            flash("Please choose a file to upload to Filecoin")
            return render_template("files.html", stored_files=stored_files)

        """TODO: ENCRYPT FILE"""

        # Push file to Filecoin via Powergate
        powergate = PowerGateClient(app.config["POWERGATE_ADDRESS"])
        # Retrieve information for default Filecoin FileSystem (FFS)
        ffs = Ffs.query.filter_by(default=True).first()
        if ffs is None:
            # No FFS exists yet so create one
            ffs = powergate.ffs.create()
            creation_date = datetime.now().replace(microsecond=0)
            filecoin_file_system = Ffs(
                ffs_id=ffs.id,
                token=ffs.token,
                creation_date=creation_date,
                default=True,
            )
            db.session.add(filecoin_file_system)
            db.session.commit()
            ffs = Ffs.query.filter_by(default=True).first()

        try:
            # Create an iterator of the uploaded file using the helper function
            file_iterator = get_file_bytes(os.path.join(upload_path, file_name))
            # Convert the iterator into request and then add to the hot set (IPFS)
            file_hash = powergate.ffs.add_to_hot(
                bytes_to_chunks(file_iterator), ffs.token
            )
            # Push the file to Filecoin
            powergate.ffs.push(file_hash.cid, ffs.token)
            # Check that CID is pinned to FFS
            check = powergate.ffs.info(file_hash.cid, ffs.token)

            # Note the upload date and file size
            upload_date = datetime.now().replace(microsecond=0)
            file_size = os.path.getsize(os.path.join(upload_path, file_name))

            """TODO: DELETE CACHED COPY OF FILE? """

            # Save file information to database
            file_upload = Files(
                file_path=upload_path,
                file_name=file_name,
                upload_date=upload_date,
                file_size=file_size,
                CID=file_hash.cid,
                ffs_id=ffs.id,
            )
            db.session.add(file_upload)
            db.session.commit()

            flash("'{}' uploaded to Filecoin.".format(file_name))

        except Exception as e:
            # Output error message if pushing to Filecoin fails
            flash("'{}' failed to upload to Filecoin. {}".format(file_name, e))

            """TODO: RESPOND TO SPECIFIC STATUS CODE DETAILS
            (how to isolate these? e.g. 'status_code.details = ...')"""

    stored_files = Files.query.all()

    return render_template("files.html", stored_files=stored_files)


@app.route("/download/<cid>", methods=["GET"])
def download(cid):
    # Retrieve File and FFS info using the CID
    file = Files.query.filter_by(CID=cid).first()
    ffs = Ffs.query.get(file.ffs_id)

    try:
        # Retrieve data from Filecoin
        powergate = PowerGateClient(app.config["POWERGATE_ADDRESS"])
        data = powergate.ffs.get(file.CID, ffs.token)

        # Save the downloaded data as a file
        # Use the default download directory configured for the app
        download_path = app.config["DOWNLOADDIR"]
        if not os.path.exists(download_path):
            os.makedirs(download_path)

        sys.stdout.buffer.write(next(data))

        """
        print(next(data)) <-- shows data in bytes format
        type(next(data))  <-- confirms it's 'byte' type
        """

        """ DOESN'T WORK:
        open(file.file_name, "wb").write(next(data))
        """

        """ ALSO DOESN'T WORK:
        bytesio_object = BytesIO(next(data))

        with open(os.path.join(download_path, file.file_name), "wb") as out_file:
            out_file.write(bytesio_object.read())
            # ALSO DOESN'T WORK: out_file.write(bytesio_object.get_buffer())
            out_file.close()
        """

        """ ALSO DOESN'T WORK:
        Path(os.path.join(download_path, file.file_name)).write_bytes(
            bytesio_object.getbuffer()
        )
        """

    except Exception as e:
        # Output error message if download from Filecoin fails
        flash("failed to download '{}' from Filecoin. {}".format(file.file_name, e))

    stored_files = Files.query.all()

    return render_template("files.html", stored_files=stored_files)


@app.route("/wallets", methods=["GET"])
def wallets():
    return render_template("wallets.html")


@app.route("/logs", methods=["GET"])
def logs():
    return render_template("logs.html")


@app.route("/settings", methods=["GET"])
def settings():
    return render_template("settings.html")
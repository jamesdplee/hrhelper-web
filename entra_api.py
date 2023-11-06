# entra_api.py

import requests
from flask import current_app as app

def get_data(token, fields=None):
    # print("get_data function called")
    headers = {
        'Authorization': 'Bearer ' + token['access_token'],
        'Content-Type': 'application/json'
    }
    if fields is None:
        fields = "id,userPrincipalName,displayName,givenName,surname,jobTitle,mobilePhone,officeLocation"
    response = requests.get(
        f"{app.config['ENDPOINT']}?$select={fields}",
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()
    result = response.json()
    # print(f"get_data result: {result}")
    return result

def update_data(token, user_id, updated_data):
    # print("update_data function called")
    headers = {
        'Authorization': 'Bearer ' + token['access_token'],
        'Content-Type': 'application/json'
    }
    try:
        response = requests.patch(
            f"{app.config['ENDPOINT']}/{user_id}",
            headers=headers,
            json=updated_data,
            timeout=30,
        )
        if response.status_code == 204:
            print("Update successful")
            return "Update successful"
        response.raise_for_status()
    except requests.exceptions.HTTPError as err:
        print(f"HTTP error occurred: {err}")
        raise
    except Exception as err:
        print(f"An error occurred: {err}")
        raise
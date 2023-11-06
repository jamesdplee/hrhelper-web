from msal import ConfidentialClientApplication
import entra_api
import werkzeug.exceptions
from flask import Flask, redirect, render_template, request, session, url_for, flash
from flask_session import Session
import json
from flask_caching import Cache
import importlib

# support entra user (delegated) and app mode in this webapp
def get_config(mode):
    if mode == 'app':
        return importlib.import_module('app_config_asapp')
    else:
        return importlib.import_module('app_config')

mode = 'user'  # default mode
app_config = get_config(mode)

app = Flask(__name__)
app.config.from_object(app_config)
assert app_config.REDIRECT_PATH != "/", "REDIRECT_PATH must not be /"
Session(app)

# This section is needed for url_for("foo", _external=True) to automatically
# generate http scheme when this sample is running on localhost,
# and to generate https scheme when it is deployed behind reversed proxy.
# See also https://flask.palletsprojects.com/en/2.2.x/deploying/proxy_fix/
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Init Entra App using id/secret from config
entra_app = ConfidentialClientApplication(
    app_config.CLIENT_ID, 
    authority=app_config.AUTHORITY,
    client_credential=app_config.CLIENT_SECRET,
)

# Initialize the cache
cache = Cache(app, config={'CACHE_TYPE': 'simple'})

# Make app_mode available to all templates
@app.context_processor
def inject_app_mode():
    app_mode = cache.get('mode') or app_config.APP_MODE
    return dict(app_mode=app_mode)

# Set the mode and use appropriate config
@app.route("/set_mode", methods=["POST"])
def set_mode():
    mode = request.form.get('mode')
    cache.set('mode', mode)
    # print(f"Mode set to: {mode}")  # Debug output
    global app_config
    app_config = get_config(mode)
    # Reinitialize entra_app with the new configuration
    global entra_app
    entra_app = ConfidentialClientApplication(
        app_config.CLIENT_ID, 
        authority=app_config.AUTHORITY,
        client_credential=app_config.CLIENT_SECRET,
    )
    # print(f"Reinitialized entra_app for '{mode}' mode")  # Debug output
    return redirect(request.referrer)

@app.route("/login")
def login():
    # Auth with Entra as-user or as-app
    mode = cache.get('mode') or app_config.APP_MODE
    # print(f"Mode: {mode}")
    if mode == 'app':
        result = entra_app.acquire_token_for_client(app_config.SCOPE)
        # print(f"Result: {result}")
        if "access_token" in result:
            return redirect(url_for("index"))
        else:
            error_message = result.get('error_description', 'Unknown error')
            print(f"Error: {error_message}")
            return render_template("error_page.html", error_message=error_message)
    else:
        # print(f"login as user mode...")
        flow = entra_app.initiate_auth_code_flow(
            app_config.SCOPE, 
            redirect_uri=url_for("auth_response", _external=True)
        )
        cache.set('flow', flow)  # Save the flow in the cache
        session["state"] = flow["state"]  # Save the state in the session
        # f"Flow: {flow}")
        return redirect(flow["auth_uri"])


@app.route(app_config.REDIRECT_PATH)
def auth_response():
    mode = cache.get('mode') or app_config.APP_MODE
    # print(f"Mode: {mode}")
    if mode == 'app':
        # print("Mode is 'app', redirecting to index page")
        return redirect(url_for("index"))  # No-OP. Goes back to Index page
    if request.args.get('state') != session.get("state"):
        # print("State mismatch, redirecting to index page")
        return redirect(url_for("index"))  # No-OP. Goes back to Index page
    if "error" in request.args:  # Authentication/Authorization failure
        # print(f"Error in request args: {request.args['error']}")
        return render_template("error_page.html", error_message=request.args['error'])
    if request.args.get('code'):
        flow = cache.get('flow')  # Get the flow from the cache
        # print(f"Flow: {flow}")
        result = entra_app.acquire_token_by_auth_code_flow(flow, request.args)
        # print(f"Result: {result}")
        if "error" in result:
            print(f"Error in result: {result['error']}")
            return render_template("error_page.html", error_message=result['error'])
        session["user"] = result.get("id_token_claims")
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear() 
    cache.clear()
    cache.set('mode', 'user')
    mode = cache.get('mode') or app_config.APP_MODE
    if mode and mode != 'app':
        logout_endpoint = "https://login.microsoftonline.com/common/oauth2/v2.0/logout"
        logout_url = logout_endpoint + "?post_logout_redirect_uri=" + url_for("index", _external=True)
        return redirect(logout_url)
    return redirect(url_for("index"))


@app.route("/")
def index():
    if not (app_config.CLIENT_ID and app_config.CLIENT_SECRET):
        raise Exception("Entra App Registration - Please ensure your application is registered, and your config contains the appropriate details.")
    user = session.get('user')
    mode = cache.get('mode') or app_config.APP_MODE
    return render_template('index.html', user=user, app_mode=mode)

@app.route("/view/<details>", methods=["GET"])
def view(details):
    mode = cache.get('mode') or app_config.APP_MODE
    if mode == 'app':
        # print(f"VIEW: Mode is 'app', acquiring token for client...")
        # print(f"VIEW: Scope: {app_config.SCOPE}")
        result = entra_app.acquire_token_for_client(app_config.SCOPE)
    else:
        # print(f"VIEW: Mode is 'user', acquiring token for user...")
        accounts = entra_app.get_accounts()
        if accounts:
            result = entra_app.acquire_token_silent(app_config.SCOPE, account=accounts[0])
        else:
            return redirect(url_for("login"))
    if "access_token" in result:
        token = {"access_token": result["access_token"]}
    else:
        error_message = result.get('error_description', 'Unknown error')
        return render_template("error_page.html", error_message=error_message)

    fields = 'id,displayName,givenName,surname' if details == 'personal' else 'id,displayName,jobTitle,mobilePhone,officeLocation'
    if details == 'all':
        fields = '*'

    api_result = entra_api.get_data(token, fields)
    return render_template('view.html', result=api_result, details=details)


@app.route("/edit/<details>", methods=["GET", "POST"])
def edit(details):
    mode = cache.get('mode') or app_config.APP_MODE
    if mode == 'app':
        # print(f"EDIT: Mode is 'app', acquiring token for client...")
        result = entra_app.acquire_token_for_client(app_config.SCOPE)
    else:
        # print(f"EDIT: Mode is 'user', acquiring token for user...")
        accounts = entra_app.get_accounts()
        if accounts:
            result = entra_app.acquire_token_silent(app_config.SCOPE, account=accounts[0])
        else:
            return redirect(url_for("login"))
    if "access_token" in result:
        token = {"access_token": result["access_token"]}
        roles = result.get("id_token_claims", {}).get("roles", [])
        # print(f"User roles in token: {roles}")
    else:
        error_message = result.get('error_description', 'Unknown error')
        return render_template("error_page.html", error_message=error_message)

    if details == 'work':
        fields = 'id,displayName,jobTitle,mobilePhone,officeLocation'
    elif details == 'personal':
        # Check the roles
        # print(f"User roles: {roles}")
        if "User.Edit.All" in roles:
            fields = 'id,displayName,givenName,surname'
        else:
            return render_template("error_page.html", error_message="You do not have permission to edit this personal details.")
    else:
        return render_template("error_page.html", error_message="Invalid details parameter.")
    
    if request.method == "POST":
        user_id = request.form.get('id') 
        updated_data = request.form.to_dict()
        success_message = entra_api.update_data(token, user_id, updated_data)  
        flash(success_message, 'success')
        api_result = entra_api.get_data(token, fields)
        return render_template('edit.html', result=api_result, details=details)
    else:
        api_result = entra_api.get_data(token, fields)
        return render_template('edit.html', result=api_result, details=details)

# Error handling
@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, werkzeug.exceptions.HTTPException):
        return e

    error_message = str(e)
    error_description = getattr(e, 'error_description', 'An unknown error occurred.')
    return render_template("error_page.html", error_message=error_message, error_description=error_description), 500

if __name__ == "__main__":
    app.run()

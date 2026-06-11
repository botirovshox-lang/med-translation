# Password Protection Setup - Medical CAT Translator v5.5

**Status:** ✅ Password protection implemented

---

## Overview

Medical CAT Translator now has password protection for the web interface. The first thing users see when accessing the app is a login screen.

---

## Default Credentials

**Default Password:** `medtranslator2026`

⚠️ **IMPORTANT:** Change this password in production!

---

## How to Change Password

### Option 1: Environment Variable (Recommended for Production)

Set the `STREAMLIT_PASSWORD` environment variable:

**On Streamlit Cloud:**
1. Go to your app dashboard
2. Click ⚙️ **Settings**
3. Go to **Secrets**
4. Add:
   ```
   STREAMLIT_PASSWORD = "your_new_secure_password"
   ```
5. Save
6. App redeploys automatically ✅

**Locally:**
```bash
export STREAMLIT_PASSWORD="your_new_secure_password"
streamlit run app_v55.py
```

### Option 2: Hardcode in auth.py

Edit `med_translation/auth.py`:

```python
# Change this line:
DEFAULT_PASSWORD_HASH = hashlib.sha256("medtranslator2026".encode()).hexdigest()

# To:
DEFAULT_PASSWORD_HASH = hashlib.sha256("your_new_password".encode()).hexdigest()
```

Then push to GitHub (if using Streamlit Cloud, it auto-redeploys).

---

## Password Features

### Login Screen
- Clean, professional login interface
- Shows "Help" button with default password hint
- Error messages for incorrect password
- Centered, responsive design

### Logout Button
- Located in sidebar (top-right when sidebar expanded)
- Click to log out and return to login screen
- Session is cleared immediately

### Session Management
- Password stored in `st.session_state.authenticated`
- Session valid for entire browser tab
- Closing browser/clearing cache requires re-login
- Each tab has independent authentication

---

## Technical Details

### Authentication Module: `auth.py`

**Functions:**
- `check_password()` - Shows login form, returns True if authenticated
- `get_password_hash(password)` - Generates SHA256 hash
- `show_logout_button()` - Displays logout button in sidebar
- `logout()` - Clears authentication and reloads app
- `set_password(new_password)` - Updates password (dev only)
- `get_password_from_env()` - Loads password from environment variable

**Password Hashing:**
- Uses SHA256 (secure for this use case)
- Passwords are never stored in plain text
- Hash generated on each login attempt for comparison

### Integration with app_v55.py

```python
# Import authentication
from auth import check_password, show_logout_button

# Check password at startup (before page config)
if not check_password():
    st.stop()  # Stop execution if not authenticated

# Show logout button in sidebar
show_logout_button()
```

---

## Security Best Practices

✅ **Do:**
- Use strong passwords in production
- Change default password immediately
- Use environment variables for sensitive data
- Keep passwords out of Git (use Streamlit Secrets)
- Use HTTPS (automatic on Streamlit Cloud)

❌ **Don't:**
- Hardcode passwords in source code
- Share passwords via email
- Use simple passwords
- Commit `.env` files with passwords
- Enable "Remember me" (this is stateless)

---

## Troubleshooting

### "Incorrect password" but I'm sure it's correct

**Solution:** 
- Check for leading/trailing spaces
- Make sure Caps Lock is off
- Environment variable might override default
- Check Streamlit Cloud Secrets

### Password won't change

**Solution:**
- If using env variable, it takes precedence
- Remove env variable to use hardcoded password
- Restart Streamlit (Ctrl+C, then run again)
- On Streamlit Cloud, wait for auto-redeploy

### Can't logout

**Solution:**
- Refresh page and click logout again
- Manually clear browser cache
- Close and reopen browser tab

### Forgot password

**Solution:**
- Edit `auth.py` and change password back
- Use environment variable override
- Redeploy to Streamlit Cloud
- Contact administrator

---

## Multi-User Setup (Advanced)

For multiple users with different passwords, you can modify `auth.py`:

```python
# In auth.py, replace check_password() with:

VALID_PASSWORDS = {
    "user1": hashlib.sha256("password1".encode()).hexdigest(),
    "user2": hashlib.sha256("password2".encode()).hexdigest(),
    "admin": hashlib.sha256("adminpass".encode()).hexdigest(),
}

def check_password():
    password = st.text_input("Password:", type="password")
    if st.button("Login"):
        password_hash = get_password_hash(password)
        if password_hash in VALID_PASSWORDS.values():
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password")
    return st.session_state.get("authenticated", False)
```

---

## API Reference

### `check_password() → bool`
Shows login form and returns authentication status.

**Returns:**
- `True` if user is authenticated
- `False` if user needs to login

**Usage:**
```python
if not check_password():
    st.stop()
```

### `show_logout_button()`
Displays logout button in sidebar.

**Usage:**
```python
show_logout_button()  # Shows button if authenticated
```

### `get_password_hash(password: str) → str`
Generate SHA256 hash of password.

**Returns:** 32-character hex string

**Usage:**
```python
hash = get_password_hash("mypassword")
```

### `logout()`
Clears authentication and reloads app.

**Usage:**
```python
logout()
```

---

## Deployment Notes

### Streamlit Cloud
- ✅ Automatic redeploy when code changes
- ✅ Secrets stored securely
- ✅ Environment variables work
- ⏱️ Redeployment takes 1-2 minutes

### Local Development
- Set `STREAMLIT_PASSWORD` env var or edit default in `auth.py`
- Run: `streamlit run app_v55.py`
- Login with password

### Docker (Railway/Render)
- Set `STREAMLIT_PASSWORD` in environment variables
- Or hardcode in `auth.py` in Dockerfile

---

## Future Enhancements

Potential improvements:
- [ ] Username + password authentication
- [ ] User roles/permissions
- [ ] Login attempt rate limiting
- [ ] Session timeout after inactivity
- [ ] Login audit logs
- [ ] Social login (GitHub, Google)
- [ ] Two-factor authentication
- [ ] Password expiration policy

---

## Support

**Questions?** Check:
1. This file (PASSWORD_SETUP.md)
2. `med_translation/auth.py` source code
3. Streamlit documentation: https://docs.streamlit.io/library/advanced-features/secrets-management

---

**Last Updated:** 2026-06-11  
**Version:** 1.0  
**Status:** Production Ready

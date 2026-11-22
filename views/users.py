"""Sign-in screen and the Users page (administrators only). Only used when RIDEOPS_REQUIRE_LOGIN is set."""
import streamlit as st

import auth
import ui


def login_screen() -> None:
    """Shown instead of the app until someone signs in. The first visit creates the administrator."""
    with st.container(width=480):
        _login_body()


def _login_body() -> None:
    st.markdown("# RideOps Support")
    ss = st.session_state
    if auth.count() == 0:
        st.info("No users yet. Create the administrator: you can add everyone else afterwards.", icon=":material/admin_panel_settings:")
        with st.form("first_admin"):
            username = st.text_input("Username")
            name = st.text_input("Your name")
            pw = st.text_input("Password", type="password", help=f"At least {auth.MIN_PASSWORD} characters.")
            pw2 = st.text_input("Repeat the password", type="password")
            if st.form_submit_button("Create administrator", type="primary", icon=":material/check:"):
                if pw != pw2:
                    st.error("The passwords do not match.", icon=":material/error:")
                else:
                    try:
                        ss.user = auth.create_user(username, name, "Admin", pw)
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e), icon=":material/error:")
        return
    with st.form("login"):
        username = st.text_input("Username")
        pw = st.text_input("Password", type="password")
        if st.form_submit_button("Sign in", type="primary", icon=":material/login:"):
            try:
                user = auth.verify(username, pw)
            except PermissionError as e:
                st.error(str(e), icon=":material/lock:")
            else:
                if user:
                    ss.user = user
                    st.rerun()
                st.error("Wrong username or password.", icon=":material/error:")


def sign_out() -> None:
    st.session_state.pop("user", None)


def users() -> None:
    ui.page_header("Admin", "Users", "Who can sign in, and what they can do. Every saved action carries the person's name.")
    me = st.session_state.get("user") or {}
    rows = auth.list_users()
    ui.dataframe([{"Username": r["username"], "Name": r["name"], "Role": r["role"], "Active": bool(r["active"]),
                   "Created": r["created_at"].replace("T", " ")} for r in rows], hide_index=True, width="stretch")

    ui.section("Add a user")
    with st.form("add_user", clear_on_submit=True, border=False):
        a, b = st.columns(2)
        username = a.text_input("Username")
        name = b.text_input("Name")
        c1, c2 = st.columns(2)
        role = c1.selectbox("Role", [r for r in auth.ROLES])
        pw = c2.text_input("Starting password", type="password", help=f"At least {auth.MIN_PASSWORD} characters. Tell the person to keep it private.")
        if st.form_submit_button("Add user", type="primary", icon=":material/person_add:"):
            try:
                auth.create_user(username, name, role, pw)
                st.toast(f"Added {username.strip().lower()}", icon=":material/check_circle:")
                st.rerun()
            except ValueError as e:
                st.error(str(e), icon=":material/error:")

    ui.section("Change a user")
    pick = st.selectbox("User", [r["username"] for r in rows], key="users_pick")
    cur = next(r for r in rows if r["username"] == pick)
    a, b = st.columns(2)
    new_role = a.selectbox("Role", auth.ROLES, index=auth.ROLES.index(cur["role"]), key=f"users_role_{pick}")
    active = b.toggle("Can sign in", value=bool(cur["active"]), key=f"users_active_{pick}")
    new_pw = st.text_input("New password (leave empty to keep it)", type="password", key=f"users_pw_{pick}")
    if st.button("Save changes", type="primary", icon=":material/save:"):
        try:
            if pick == me.get("username") and (not active or new_role != "Admin"):
                raise ValueError("You cannot remove your own administrator access. Ask another administrator.")
            auth.update_user(pick, role=new_role, active=active, password=new_pw or None)
            st.toast(f"Saved {pick}", icon=":material/check_circle:")
            st.rerun()
        except ValueError as e:
            st.error(str(e), icon=":material/error:")

// The admin token (ADMIN_TOKEN on the server), kept in this browser once it has been entered.
// Storage can be blocked, so a missing token is the same as none.
const STORAGE_KEY = 'bradley-admin-token';
export const AUTH_REQUIRED_EVENT = 'bradley-admin-auth-required';

export const getAdminToken = () => {
  try {
    return localStorage.getItem(STORAGE_KEY) || '';
  } catch {
    return '';
  }
};

export const setAdminToken = (token) => {
  try {
    if (token) localStorage.setItem(STORAGE_KEY, token);
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // the token then lasts only until the page reloads
  }
};

export const authHeaders = () => {
  const token = getAdminToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
};

// The server refused the token (or there wasn't one): forget it and let the admin screen ask again
export const authRequired = () => {
  setAdminToken('');
  window.dispatchEvent(new Event(AUTH_REQUIRED_EVENT));
};

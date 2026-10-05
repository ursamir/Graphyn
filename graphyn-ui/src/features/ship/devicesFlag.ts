/**
 * Feature flag: the Devices tab (Ship → Devices, /devices) stays hidden until a
 * device registry / flash / OTA API exists. While false, Ship shows Package only
 * and any devices URL redirects to Ship (or shows a plain "not available" page).
 */
export const DEVICES_ENABLED: boolean = false

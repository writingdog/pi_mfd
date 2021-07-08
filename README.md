# pi_mfd_proxy
Using Raspberry Pi to emulate a USB device

Based on Milador's work here: https://github.com/milador/RaspberryPi-Joystick

This uses the USB gadget definition to create a virtual USB device with:

32 buttons
2 4-way hat switches (so +16 logical buttons)
2 axes

When run on a Raspberry Pi supporting USB OTG, i.e. a Raspberry Pi 4, this can then be plugged into a Windows computer and used as an arbitrary game controller. The included MFD HTML file is designed to run on a screen behind one of Thrustmaster's "Cougar MFD" panels, and shows the current state of each OSB as defined within the app.

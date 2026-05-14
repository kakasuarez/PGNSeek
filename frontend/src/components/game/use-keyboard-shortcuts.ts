import { useEffect, useRef } from "react";

export function useKeyboardShortcuts(callback: () => void, keyCodes: string[]): void {
	const callbackRef = useRef(callback);
	const keyCodesRef = useRef(keyCodes);

	useEffect(() => {
		callbackRef.current = callback;
	}, [callback]);

	useEffect(() => {
		keyCodesRef.current = keyCodes;
	}, [keyCodes]);

	useEffect(() => {
		const handler = ({ code }: KeyboardEvent) => {
			if (keyCodesRef.current.includes(code)) {
				callbackRef.current();
			}
		};

		window.addEventListener("keydown", handler);
		return () => {
			window.removeEventListener("keydown", handler);
		};
	}, []);
}
}
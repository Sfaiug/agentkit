package terminal

// Keyboard is a later slice's on Windows, where ak leaves the terminal to Python's road: exit 3
// before anything here is reached.
type Keyboard struct{}

func NewKeyboard() *Keyboard       { return &Keyboard{} }
func (k *Keyboard) Take()          {}
func (k *Keyboard) Give()          {}
func (k *Keyboard) Sense()         {}
func (k *Keyboard) Wake()          {}
func (k *Keyboard) Screen() Screen { return Screen{} }
func (k *Keyboard) ReadKey() Key   { return Key{Name: "eof"} }
func (k *Keyboard) Unread(...Key)  {}
func (k *Keyboard) Drop()          {}
